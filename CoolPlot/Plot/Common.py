# -*- coding: utf-8 -*-
from __future__ import print_function, division

import matplotlib
import matplotlib.pyplot as plt

import numpy as np
from abc import ABCMeta
from six import with_metaclass
import warnings

import CoolProp
from CoolProp import AbstractState
from CoolProp import CoolProp as CP
from CoolProp.CoolProp import PropsSI, extract_backend, extract_fractions, PyCriticalState

from ..Util.Units import SIunits, KSIunits, EURunits
from ..Util import is_string, _get_index
from ..Util.EnhancedState import process_fluid_state, EnhancedState


def interpolate_values_1d(x, y, x_points=None, kind='linear'):
    try:
        from scipy.interpolate.interpolate import interp1d
        if x_points is None:
            return interp1d(x, y, kind=kind)(x[np.isfinite(x)])
        else:
            return interp1d(x, y, kind=kind)(x_points)
    except ImportError:
        if kind != 'linear':
            warnings.warn(
              "You requested a non-linear interpolation, but SciPy is not available. Falling back to linear interpolation.",
              UserWarning)
        if x_points is None:
            return np.interp((x[np.isfinite(x)]), x, y)
        else:
            return np.interp(x_points, x, y)




class Base2DObject(with_metaclass(ABCMeta), object):
    """A container for shared settings and constants for the
    isolines and the property plots."""

    # A list of supported plot
    TS = CoolProp.iT * 10 + CoolProp.iSmass
    PH = CoolProp.iP * 10 + CoolProp.iHmass
    HS = CoolProp.iHmass * 10 + CoolProp.iSmass
    PS = CoolProp.iP * 10 + CoolProp.iSmass
    PD = CoolProp.iP * 10 + CoolProp.iDmass
    TD = CoolProp.iT * 10 + CoolProp.iDmass
    PT = CoolProp.iP * 10 + CoolProp.iT
    PU = CoolProp.iP * 10 + CoolProp.iUmass

    PLOTS = {
      'TS': TS,
      'PH': PH,
      'HS': HS,
      'PS': PS,
      'PD': PD,
      'TD': TD,
      'PT': PT,
    }

    PLOTS_INV = {v: k for k, v in PLOTS.items()}

#     # A list of supported plot
#     @property
#     def TS(self): return type(self).TS
#     @property
#     def PH(self): return CoolProp.iP*10     + CoolProp.iHmass
#     @property
#     def HS(self): return CoolProp.iHmass*10 + CoolProp.iSmass
#     @property
#     def PS(self): return CoolProp.iP*10     + CoolProp.iSmass
#     @property
#     def PD(self): return CoolProp.iP*10     + CoolProp.iDmass
#     @property
#     def TD(self): return CoolProp.iT*10     + CoolProp.iDmass
#     @property
#     def PT(self): return CoolProp.iP*10     + CoolProp.iT
#     @property
#     def PU(self): return CoolProp.iP*10     + CoolProp.iUmass

    def __init__(self, x_type, y_type, state=None, small=None, **kwargs):
        self._x_index = _get_index(x_type)
        self._y_index = _get_index(y_type)

        if small is not None: self._small = small
        else: self._small = 1e-7

        if state is not None: self.state = state
        else: self._state = None

    # A list of supported plot
    @property
    def x_index(self): return self._x_index

    @property
    def y_index(self): return self._y_index

    @property
    def critical_state(self):
        if self.state is not None:
            return self.state.critical_state
        return None

    @property
    def state(self): return self._state

    @state.setter
    def state(self, value):
        self._state = process_fluid_state(value)
        self._T_small = self.critical_state.keyed_output(CoolProp.iT) * self._small
        self._P_small = self.critical_state.keyed_output(CoolProp.iP) * self._small

    def _get_sat_bounds(self, kind, smin=None, smax=None):
        """Generates limits for the saturation line in either T or p determined
        by 'kind'. If smin or smax are provided, values will be checked
        against the allowable range for the EOS and a warning might be
        generated. Returns a tuple containing (xmin, xmax)"""

        # TODO: REFPROP backend does not have ptriple.
        T_triple = self.state.trivial_keyed_output(CoolProp.iT_triple)
        try:
            T_min = self.state.trivial_keyed_output(CoolProp.iT_min)
        except:
            T_min = T_triple
        self.state.update(CoolProp.QT_INPUTS, 0, max([T_triple, T_min]) + self._T_small)
        kind = _get_index(kind)
        if kind == CoolProp.iP:
            fluid_min = self.state.keyed_output(CoolProp.iP) + self._P_small
            fluid_max = self.critical_state.keyed_output(CoolProp.iP) - self._P_small
        elif kind == CoolProp.iT:
            fluid_min = self.state.keyed_output(CoolProp.iT) + self._T_small
            fluid_max = self.critical_state.keyed_output(CoolProp.iT) - self._T_small
        else:
            raise ValueError("Saturation boundaries have to be defined in T or P, but not in {0:s}".format(str(kind)))

        if smin is not None:
            if fluid_min < smin < fluid_max:
                sat_min = smin
            else:
                warnings.warn(
                  "Your minimum {0:s} has been ignored, {1:f} is not between {2:f} and {3:f}".format(self.PROPERTIES[kind], smin, fluid_min, fluid_max),
                  UserWarning)
                sat_min = fluid_min
        else:
            sat_min = fluid_min

        if smax is not None:
            if fluid_min < smax < fluid_max:
                sat_max = smax
            else:
                warnings.warn(
                  "Your maximum {0:s} has been ignored, {1:f} is not between {2:f} and {3:f}".format(self.PROPERTIES[kind], smax, fluid_min, fluid_max),
                  UserWarning)
                sat_max = fluid_max
        else:
            sat_max = fluid_max

        return sat_min, sat_max


class IsoLine(Base2DObject):
    """An object that holds the functions to calculate a line of
    a constant property in the dimensions of a property plot. This
    class only uses SI units."""

    # Normally we calculate a sweep in x-dimensions, but
    # sometimes a sweep in y-dimensions is better.
    XY_SWITCH = {
      CoolProp.iDmass: {Base2DObject.TS: True, Base2DObject.PH: True, Base2DObject.HS: False, Base2DObject.PS: True, Base2DObject.PD: None, Base2DObject.TD: None, Base2DObject.PT: False},
      CoolProp.iHmass: {Base2DObject.TS: False, Base2DObject.PH: None, Base2DObject.HS: None, Base2DObject.PS: True, Base2DObject.PD: True, Base2DObject.TD: False, Base2DObject.PT: False},
      CoolProp.iP: {Base2DObject.TS: False, Base2DObject.PH: None, Base2DObject.HS: False, Base2DObject.PS: None, Base2DObject.PD: None, Base2DObject.TD: False, Base2DObject.PT: None},
      CoolProp.iSmass: {Base2DObject.TS: None, Base2DObject.PH: True, Base2DObject.HS: None, Base2DObject.PS: None, Base2DObject.PD: True, Base2DObject.TD: False, Base2DObject.PT: True},
      CoolProp.iT: {Base2DObject.TS: None, Base2DObject.PH: True, Base2DObject.HS: False, Base2DObject.PS: False, Base2DObject.PD: False, Base2DObject.TD: None, Base2DObject.PT: None},
      CoolProp.iQ: {Base2DObject.TS: True, Base2DObject.PH: True, Base2DObject.HS: True, Base2DObject.PS: True, Base2DObject.PD: True, Base2DObject.TD: True, Base2DObject.PT: False}
    }

    # Abort interpolation if there are not enough
    # valid entries.
    VALID_REQ = 5.0 / 100.0

    def __init__(self, i_index, x_index, y_index, value=0.0, state=None):
        super(IsoLine, self).__init__(x_index, y_index, state)
        self._i_index = _get_index(i_index)
        if value is not None: self.value = value
        else: self._value = None
        self._x = None
        self._y = None

    @property
    def i_index(self): return self._i_index

    @property
    def value(self): return self._value

    @value.setter
    def value(self, value): self._value = float(value)

    @property
    def x(self): return self._x

    @x.setter
    def x(self, value): self._x = np.array(value)

    @property
    def y(self): return self._y

    @y.setter
    def y(self, value): self._y = np.array(value)

    def get_update_pair(self):
        """Processes the values for the isoproperty and the graph dimensions
        to figure which should be used as inputs to the state update. Returns
        a tuple with the indices for the update call and the property constant.
        For an isobar in a Ts-diagram it returns the default order and the
        correct constant for the update pair:
        get_update_pair(CoolProp.iP,CoolProp.iSmass,CoolProp.iT) -> (0,1,2,CoolProp.PSmass_INPUTS)
        other values require switching and swapping.
        """
        # Figure out if x or y-dimension should be used
        switch = self.XY_SWITCH[self.i_index][self.y_index * 10 + self.x_index]

        if switch is None:
            raise ValueError("This isoline cannot be calculated!")
        elif switch is False:
            pair, out1, _ = CP.generate_update_pair(self.i_index, 0.0, self.x_index, 1.0)
        elif switch is True:
            pair, out1, _ = CP.generate_update_pair(self.i_index, 0.0, self.y_index, 1.0)
        else:
            raise ValueError("Unknown error!")

        if out1 == 0.0:  # Correct order
            swap = False
        else:  # Wrong order
            swap = True

        if not switch and not swap:
            return 0, 1, 2, pair
        elif switch and not swap:
            return 0, 2, 1, pair
        elif not switch and swap:
            return 1, 0, 2, pair
        elif switch and swap:
            return 1, 2, 0, pair
        else:
            raise ValueError("Check the code, this should not happen!")

    def calc_sat_range(self, Trange=None, Prange=None, num=200):
        if Trange is not None:
            two = np.array(Trange)
            one = np.resize(np.array(self.value), two.shape)
            pair = CoolProp.QT_INPUTS
        elif Prange is not None:
            one = np.array(Prange)
            two = np.resize(np.array(self.value), one.shape)
            pair = CoolProp.PQ_INPUTS
        else:
            T_lo, T_hi = self._get_sat_bounds(CoolProp.iT)
            two = np.linspace(T_lo, T_hi, num)
            one = np.resize(np.array(self.value), two.shape)
            pair = CoolProp.QT_INPUTS

        Tcrit = self.critical_state.keyed_output(CoolProp.iT)
        Pcrit = self.critical_state.keyed_output(CoolProp.iP)
        Dcrit = self.critical_state.keyed_output(CoolProp.iDmass)
        try:
            #self.state.update(CoolProp.DmassT_INPUTS, Dcrit, Tcrit)
            #xcrit = self.state.keyed_output(self._x_index)
            #ycrit = self.state.keyed_output(self._y_index)
            xcrit = self.critical_state.keyed_output(self._x_index)
            ycrit = self.critical_state.keyed_output(self._y_index)
        except:
            warnings.warn(
              "An error occurred for the critical inputs, skipping it.",
              UserWarning)
            xcrit = np.NaN
            ycrit = np.NaN

        X = np.empty_like(one)
        Y = np.empty_like(one)

        err = False
        for index, _ in np.ndenumerate(one):
            try:
                self.state.update(pair, one[index], two[index])
                X[index] = self.state.keyed_output(self._x_index)
                Y[index] = self.state.keyed_output(self._y_index)
            except Exception as e:
                if (pair == CoolProp.QT_INPUTS and abs(two[index] - Tcrit) < 1e0) or \
                   (pair == CoolProp.PQ_INPUTS and abs(one[index] - Pcrit) < 1e2):
                    X[index] = xcrit
                    Y[index] = ycrit
                    warnings.warn(
                  "An error occurred for near critical inputs {0:f}, {1:f} with index {2:s}: {3:s}".format(one[index], two[index], str(index), str(e)),
                  UserWarning)
                    pass

                warnings.warn(
                  "An error occurred for inputs {0:f}, {1:f} with index {2:s}: {3:s}".format(one[index], two[index], str(index), str(e)),
                  UserWarning)
                X[index] = np.NaN
                Y[index] = np.NaN
                err = True
        self.x = X; self.y = Y
        return

    def calc_range(self, xvals=None, yvals=None):

        if self.i_index == CoolProp.iQ:
            warnings.warn(
                "Please use \"calc_sat_range\" to calculate saturation and isoquality lines. Input ranges are discarded.",
                UserWarning)
            if xvals is not None: self.calc_sat_range(num=xvals.size)
            elif yvals is not None: self.calc_sat_range(num=yvals.size)
            else: self.calc_sat_range()
            return

        ipos, xpos, ypos, pair = self.get_update_pair()

        order = [ipos, xpos, ypos]
        idxs = [v for (_, v) in sorted(zip(order, [self.i_index, self.x_index, self.y_index]))]
        vals = [v for (_, v) in sorted(zip(order, [np.array(self.value), xvals, yvals]))]
        if vals[0] is None or vals[1] is None:
            raise ValueError("One required input is missing, make sure to supply the correct xvals ({0:s}) or yvals ({1:s}).".format(str(xvals), str(yvals)))

        if vals[0].size > vals[1].size:
            vals[1] = np.resize(vals[1], vals[0].shape)
        elif vals[0].size < vals[1].size:
            vals[0] = np.resize(vals[0], vals[1].shape)

        vals[2] = np.empty_like(vals[0])
        err = False
        guesses = CoolProp.CoolProp.PyGuessesStructure()
        # Only use the guesses for selected inputs
        if pair == CoolProp.HmolarP_INPUTS \
          or pair == CoolProp.HmassP_INPUTS:
            # or pair == CoolProp.HmassSmass_INPUTS \
            # or pair == CoolProp.HmolarSmolar_INPUTS \
            # or pair == CoolProp.PSmass_INPUTS \
            # or pair == CoolProp.PSmolar_INPUTS:
            use_guesses = True
        else:
            use_guesses = False
        for index, _ in np.ndenumerate(vals[0]):
            try:
                if use_guesses:
                    if np.isfinite(guesses.rhomolar):
                        self.state.update_with_guesses(pair, vals[0][index], vals[1][index], guesses)
                    else:
                        self.state.update(pair, vals[0][index], vals[1][index])
                    guesses.rhomolar = self.state.rhomolar()
                    guesses.T = self.state.T()
                else:
                    self.state.update(pair, vals[0][index], vals[1][index])
                vals[2][index] = self.state.keyed_output(idxs[2])
            except Exception as e:
                warnings.warn(
                  "An error occurred for inputs {0:f}, {1:f} with index {2:s}: {3:s}".format(vals[0][index], vals[1][index], str(index), str(e)),
                  UserWarning)
                vals[2][index] = np.NaN
                guesses.rhomolar = np.NaN
                guesses.T = np.NaN
                err = True

        for i, v in enumerate(idxs):
            if v == self.x_index: self.x = vals[i]
            if v == self.y_index: self.y = vals[i]

    def sanitize_data(self):
        """Fill the series via interpolation"""
        validx = None; validy = None
        countx = None; county = None
        if self.x is not None:
            validx = np.isfinite(self.x)
            countx = float(self.x.size)
        else:
            raise ValueError("The x-axis is not populated, calculate values before you interpolate.")
        if self.y is not None:
            validy = np.isfinite(self.y)
            county = float(self.y.size)
        else:
            raise ValueError("The y-axis is not populated, calculate values before you interpolate.")

        if min([np.sum(validx) / countx, np.sum(validy) / county]) < self.VALID_REQ:
            warnings.warn(
              "Poor data quality, there are not enough valid entries for x ({0:f}/{1:f}) or y ({2:f}/{3:f}).".format(np.sum(validx), countx, np.sum(validy), county),
              UserWarning)
        # TODO: use filter and cubic splines!
        #filter = np.logical_and(np.isfinite(self.x),np.isfinite(self.y))
        if np.sum(validy) > np.sum(validx):
            self.x = interpolate_values_1d(self.y, self.x, x_points=self.y[validy])
            self.y = self.y[validy]
        else:
            self.y = interpolate_values_1d(self.x, self.y, x_points=self.x[validx])
            self.x = self.x[validx]


class BasePlot(Base2DObject):
    """The base class for all plots. It can be instantiated itself, but provides many
    general facilities to be used in the different plots. """

    # Define the iteration keys
    PROPERTIES = {
      CoolProp.iDmass: 'density',
      CoolProp.iHmass: 'specific enthalpy',
      CoolProp.iP: 'pressure',
      CoolProp.iSmass: 'specific entropy',
      CoolProp.iT: 'temperature',
      CoolProp.iUmass: 'specific internal energy'
    }

    # Define the unit systems
    UNIT_SYSTEMS = {
      'SI': SIunits(),
      'KSI': KSIunits(),
      'EUR': EURunits()
    }

    LINE_PROPS = {
      CoolProp.iT: dict(color='Darkred', lw=0.25),
      CoolProp.iP: dict(color='DarkCyan', lw=0.25),
      CoolProp.iHmass: dict(color='DarkGreen', lw=0.25),
      CoolProp.iDmass: dict(color='DarkBlue', lw=0.25),
      CoolProp.iSmass: dict(color='DarkOrange', lw=0.25),
      CoolProp.iQ: dict(color='black', lw=0.25)
    }

    ID_FACTOR = 10.0  # Values below this number are interpreted as factors
    HI_FACTOR = 2.25  # Upper default limits: HI_FACTOR*T_crit and HI_FACTOR*p_crit
    LO_FACTOR = 1.01  # Lower default limits: LO_FACTOR*T_triple and LO_FACTOR*p_triple

    TP_LIMITS = {
      'NONE': [None, None, None, None],
      'DEF': [LO_FACTOR, HI_FACTOR, LO_FACTOR, HI_FACTOR],
      'ACHP': [173.15, 493.15, 0.25e5, HI_FACTOR],
      'ORC': [273.15, 673.15, 0.25e5, HI_FACTOR]
    }

    def __init__(self, fluid_ref, graph_type, unit_system='KSI', tp_limits='DEF', **kwargs):

        # Process the graph_type and set self._x_type and self._y_type
        graph_type = graph_type.upper()
        graph_type = graph_type.replace(r'RHO', r'D')
        if graph_type not in Base2DObject.PLOTS:
            raise ValueError("Invalid graph_type input, expected a string from {0:s}".format(str(self.PLOTS)))

        # Process the unit_system and set self._system
        self.system = unit_system
        # Process the plotting range based on T and p
        self.limits = tp_limits
        # Other properties
        #self.figure = kwargs.pop('figure', plt.figure(tight_layout=True))

        self.figure = kwargs.get('figure', matplotlib.figure.Figure(tight_layout=True))
        if 'axis' in kwargs and 'axes' not in kwargs:
            kwargs['axes'] = kwargs['axis']
        self.axes = kwargs.get('axes', self.figure.add_subplot(111))
        self.props = kwargs.get('props', None)

        # call the base class
        state = process_fluid_state(fluid_ref)
        Base2DObject.__init__(self, graph_type[1], graph_type[0], state, **kwargs)

    @property
    def system(self): return self._system

    @system.setter
    def system(self, value):
        value = value.upper()
        if value in self.UNIT_SYSTEMS: self._system = self.UNIT_SYSTEMS[value]
        else: raise ValueError("Invalid input, expected a string from {0:s}".format(str(self.UNIT_SYSTEMS.keys())))

    @property
    def limits(self):
        """Returns [Tmin,Tmax,pmin,pmax] as value or factors"""
        return self._limits

    @limits.setter
    def limits(self, value):
        if is_string(value):
            value = value.upper()
        if value in self.TP_LIMITS:
            self._limits = self.TP_LIMITS[value]
        elif len(value) == 4:
            self._limits = value
        else:
            raise ValueError("Invalid input, expected a list with 4 items or a string from {0:s}".format(str(self.TP_LIMITS.keys())))

    @property
    def figure(self): return self._figure

    @figure.setter
    def figure(self, value): self._figure = value

    @property
    def axis(self):
        warnings.warn("You use the deprecated property \"axis\", please use \"axes\" instead", DeprecationWarning)
        return self._axes

    @axis.setter
    def axis(self, value):
        warnings.warn("You use the deprecated property \"axis\", please use \"axes\" instead", DeprecationWarning)
        self._axes = value

    @property
    def axes(self): return self._axes

    @axes.setter
    def axes(self, value): self._axes = value

    @property
    def props(self): return self._props

    @props.setter
    def props(self, value):
        self._props = self.LINE_PROPS.copy()
        if value is not None:
            self._props.update(value)

    def __sat_bounds(self, kind, smin=None, smax=None):
        warnings.warn(
          "You called the deprecated function \"__sat_bounds\", \
consider replacing it with \"_get_sat_bounds\".",
          DeprecationWarning)
        return self._get_sat_bounds(kind, smin, smax)

    def _get_iso_label(self, isoline, unit=True):
        if self._system is not None:
            dim = self._system[isoline.i_index]
            return str(r"$" + dim.symbol + "=" + str(dim.from_SI(isoline.value)) + "$ " + dim.unit if unit else "$").strip()
        return str(isoline.value).strip()

    # def _get_phase_envelope(self):
    #
    #HEOS = CoolProp.AbstractState("HEOS", fluid)
    # HEOS.build_phase_envelope("")
    #PED = HEOS.get_phase_envelope_data()
    #plt.plot(PED.T, np.log(PED.p))
    # plt.show()

    def _plot_default_annotations(self):
#         def filter_fluid_ref(fluid_ref):
#             fluid_ref_string = fluid_ref
#             if fluid_ref.startswith('REFPROP-MIX'):
#                 end = 0
#                 fluid_ref_string = ''
#                 while fluid_ref.find('[', end + 1) != -1:
#                     start = fluid_ref.find('&', end + 1)
#                     if end == 0:
#                         start = fluid_ref.find(':', end + 1)
#                     end = fluid_ref.find('[', end + 1)
#                     fluid_ref_string = ' '.join([fluid_ref_string,
#                                                 fluid_ref[start+1:end], '+'])
#                 fluid_ref_string = fluid_ref_string[0:len(fluid_ref_string)-2]
#             return fluid_ref_string
#
#         if len(self.graph_type) == 2:
#             y_axis_id = self.graph_type[0]
#             x_axis_id = self.graph_type[1]
#         else:
#             y_axis_id = self.graph_type[0]
#             x_axis_id = self.graph_type[1:len(self.graph_type)]
#
#         tl_str = "%s - %s Graph for %s"
#         if not self.axes.get_title():
#             self.axes.set_title(tl_str % (self.AXIS_LABELS[self.unit_system][y_axis_id][0],
#                                           self.AXIS_LABELS[self.unit_system][x_axis_id][0],
#                                           filter_fluid_ref(self.fluid_ref)))
        if self._x_index in [CoolProp.iDmass, CoolProp.iP]:
            self.axes.set_xscale('log')
        if self._y_index in [CoolProp.iDmass, CoolProp.iP]:
            self.axes.set_yscale('log')

        if not self.axes.get_xlabel():
            dim = self._system[self._x_index]
            self.xlabel((dim.label + u" $" + dim.symbol + u"$ / " + dim.unit).strip())
        if not self.axes.get_ylabel():
            dim = self._system[self._y_index]
            self.ylabel((dim.label + u" $" + dim.symbol + u"$ / " + dim.unit).strip())

    def title(self, title):
        self.axes.set_title(title)

    def xlabel(self, xlabel):
        self.axes.set_xlabel(xlabel)

    def ylabel(self, ylabel):
        self.axes.set_ylabel(ylabel)

    def grid(self, b=None, **kwargs):
        g_map = {'on': True, 'off': False}
        if b is not None:
            b = g_map[b.lower()]
        if not kwargs:  # len=0
            self.axes.grid(b)
        else:
            self.axes.grid(kwargs)

    def set_Tp_limits(self, limits):
        """Set the limits for the graphs in temperature and pressure, based on
        the active units: [Tmin, Tmax, pmin, pmax]"""
        dim = self._system[CoolProp.iT]
        limits[0] = dim.to_SI(limits[0])
        limits[1] = dim.to_SI(limits[1])
        dim = self._system[CoolProp.iP]
        limits[2] = dim.to_SI(limits[2])
        limits[3] = dim.to_SI(limits[3])
        self.limits = limits

    def get_Tp_limits(self):
        """Get the limits for the graphs in temperature and pressure, based on
        the active units: [Tmin, Tmax, pmin, pmax]"""
        limits = self._get_Tp_limits()
        dim = self._system[CoolProp.iT]
        limits[0] = dim.from_SI(limits[0])
        limits[1] = dim.from_SI(limits[1])
        dim = self._system[CoolProp.iP]
        limits[2] = dim.from_SI(limits[2])
        limits[3] = dim.from_SI(limits[3])
        return limits

    def _get_Tp_limits(self):
        """Get the limits for the graphs in temperature and pressure, based on
        SI units: [Tmin, Tmax, pmin, pmax]"""
        T_lo, T_hi, P_lo, P_hi = self.limits
        Ts_lo, Ts_hi = self._get_sat_bounds(CoolProp.iT)
        Ps_lo, Ps_hi = self._get_sat_bounds(CoolProp.iP)

        if T_lo is None: T_lo = 0.0
        elif T_lo < self.ID_FACTOR: T_lo *= Ts_lo
        if T_hi is None: T_hi = 1e6
        elif T_hi < self.ID_FACTOR: T_hi *= Ts_hi
        if P_lo is None: P_lo = 0.0
        elif P_lo < self.ID_FACTOR: P_lo *= Ps_lo
        if P_hi is None: P_hi = 1e10
        elif P_hi < self.ID_FACTOR: P_hi *= Ps_hi

        try: T_lo = np.nanmax([T_lo, self.state.trivial_keyed_output(CoolProp.iT_min)])
        except: pass
        try: T_hi = np.nanmin([T_hi, self.state.trivial_keyed_output(CoolProp.iT_max)])
        except: pass
        try: P_lo = np.nanmax([P_lo, self.state.trivial_keyed_output(CoolProp.iP_min)])
        except: pass
        try: P_hi = np.nanmin([P_hi, self.state.trivial_keyed_output(CoolProp.iP_max)])
        except: pass

        return [T_lo, T_hi, P_lo, P_hi]

    def set_axis_limits(self, limits):
        """Set the limits of the internal axes object based on the active units,
        takes [xmin, xmax, ymin, ymax]"""
        self.axes.set_xlim([limits[0], limits[1]])
        self.axes.set_ylim([limits[2], limits[3]])

    def set_axis_limits_SI(self, limits):
        """Set the limits of the internal axes object based on SI units,
        takes [xmin, xmax, ymin, ymax]"""
        dim = self._system[self._x_index]
        self.axes.set_xlim([dim.from_SI(limits[0]), dim.from_SI(limits[1])])
        dim = self._system[self._y_index]
        self.axes.set_ylim([dim.from_SI(limits[2]), dim.from_SI(limits[3])])

    def get_axis_limits(self, x_index=None, y_index=None):
        """Returns the previously set limits or generates them and
        converts the default values to the selected unit system.
        Returns a list containing [xmin, xmax, ymin, ymax]"""
        if x_index is None: x_index = self._x_index
        if y_index is None: y_index = self._y_index

        if x_index != self.x_index or y_index != self.y_index or \
          self.axes.get_autoscalex_on() or self.axes.get_autoscaley_on():
            # One of them is not set or we work on a different set of axes
            T_lo, T_hi, P_lo, P_hi = self._get_Tp_limits()

            X = [0.0] * 4; Y = [0.0] * 4
            i = -1
            for T in [T_lo, T_hi]:
                for P in [P_lo, P_hi]:
                    i += 1
                    try:
                        self.state.update(CoolProp.PT_INPUTS, P, T)
                        # TODO: include a check for P and T?
                        X[i] = self.state.keyed_output(x_index)
                        Y[i] = self.state.keyed_output(y_index)
                    except:
                        X[i] = np.nan; Y[i] = np.nan
            # Figure out what to update
            dim = self._system[x_index]
            x_lim = [dim.from_SI(np.nanmin(X)), dim.from_SI(np.nanmax(X))]
            dim = self._system[y_index]
            y_lim = [dim.from_SI(np.nanmin(Y)), dim.from_SI(np.nanmax(Y))]
            # Either update the axes limits or get them
            if x_index == self._x_index:
                if self.axes.get_autoscalex_on():
                    self.axes.set_xlim(x_lim)
                else:
                    x_lim = self.axes.get_xlim()
            if y_index == self._y_index:
                if self.axes.get_autoscaley_on():
                    self.axes.set_ylim(y_lim)
                else:
                    y_lim = self.axes.get_ylim()
        else:  # We only asked for the real axes limits and they are set already
            x_lim = self.axes.get_xlim()
            y_lim = self.axes.get_ylim()

        return [x_lim[0], x_lim[1], y_lim[0], y_lim[1]]

    def get_axis_limits_SI(self, x_index=None, y_index=None):
        """Get the limits of the internal axes object in SI units
        Returns a list containing [xmin, xmax, ymin, ymax]"""
        if x_index is None: x_index = self._x_index
        if y_index is None: y_index = self._y_index
        limits = self.get_axis_limits(x_index, y_index)
        dim = self._system[x_index]
        limits[0] = dim.to_SI(limits[0])
        limits[1] = dim.to_SI(limits[1])
        dim = self._system[y_index]
        limits[2] = dim.to_SI(limits[2])
        limits[3] = dim.to_SI(limits[3])
        return limits

    @staticmethod
    def generate_ranges(itype, imin, imax, num):
        """Generate a range for a certain property"""
        if itype in [CoolProp.iP, CoolProp.iDmass]:
            return np.logspace(np.log2(imin), np.log2(imax), num=num, base=2.)
        return np.linspace(imin, imax, num=num)

    def _get_conversion_data(self):
        [Axmin, Axmax, Aymin, Aymax] = self.get_axis_limits_SI()
        DELTAX_axis = Axmax - Axmin
        DELTAY_axis = Aymax - Aymin
        width = self.figure.get_figwidth()
        height = self.figure.get_figheight()
        pos = self.axes.get_position().get_points()
        [[Fxmin, Fymin], [Fxmax, Fymax]] = pos
        DELTAX_fig = width * (Fxmax - Fxmin)
        DELTAY_fig = height * (Fymax - Fymin)
        return [[Axmin, Axmax, Aymin, Aymax, Fxmin, Fxmax, Fymin, Fymax], [DELTAX_axis, DELTAY_axis, DELTAX_fig, DELTAY_fig]]

    def _to_pixel_coords(self, xv, yv):
        [[Axmin, Axmax, Aymin, Aymax, Fxmin, Fxmax, Fymin, Fymax], [DELTAX_axis, DELTAY_axis, DELTAX_fig, DELTAY_fig]] = self._get_conversion_data()
        # Convert coords to pixels
        x = (xv - Axmin) / DELTAX_axis * DELTAX_fig + Fxmin
        y = (yv - Aymin) / DELTAY_axis * DELTAY_fig + Fymin
        return x, y

    def _to_data_coords(self, xv, yv):
        [[Axmin, Axmax, Aymin, Aymax, Fxmin, Fxmax, Fymin, Fymax], [DELTAX_axis, DELTAY_axis, DELTAX_fig, DELTAY_fig]] = self._get_conversion_data()
        # Convert back to measurements
        x = (xv - Fxmin) / DELTAX_fig * DELTAX_axis + Axmin
        y = (yv - Fymin) / DELTAY_fig * DELTAY_axis + Aymin
        return x, y

    @staticmethod
    def get_x_y_dydx(xv, yv, x):
        """Get x and y coordinates and the linear interpolation derivative"""
        # Old implementation:
        # Get the rotation angle
        #f = interp1d(xv, yv)
        #y = f(x)
        #h = 0.00001*x
        #dy_dx = (f(x+h)-f(x-h))/(2*h)
        # return x,y,dy_dx
        if len(xv) == len(yv) and len(yv) > 1:  # assure same length
            if len(xv) == len(yv) and len(yv) == 2:  # only two points
                if np.min(xv) < x < np.max(xv):
                    dx = xv[1] - xv[0]
                    dy = yv[1] - yv[0]
                    dydx = dy / dx
                    y = yv[0] + dydx * (x - xv[0])
                    return x, y, dydx
                else:
                    raise ValueError("Your coordinate has to be between the input values.")
            else:
                limit = 1e-10                    # avoid hitting a point directly
                diff = np.array(xv) - x        # get differences
                index = np.argmin(diff * diff)  # nearest neighbour
                if (xv[index] < x < xv[index + 1]      # nearest below, positive inclination
                  or xv[index] > x > xv[index + 1]):   # nearest above, negative inclination
                    if diff[index] < limit:
                        index = [index - 1, index + 1]
                    else:
                        index = [index, index + 1]
                elif (xv[index - 1] < x < xv[index]    # nearest above, positive inclination
                  or xv[index - 1] > x > xv[index]):   # nearest below, negative inclination
                    if diff[index] < limit:
                        index = [index - 1, index + 1]
                    else:
                        index = [index - 1, index]
                xvnew = xv[index]
                yvnew = yv[index]
                return BasePlot.get_x_y_dydx(xvnew, yvnew, x)  # Allow for a single recursion
        else:
            raise ValueError("You have to provide the same amount of x- and y-pairs with at least two entries each.")

    def _inline_label(self, xv, yv, x=None, y=None):
        """
        This will give the coordinates and rotation required to align a label with
        a line on a plot in SI units.
        """
        if y is None and x is not None:
            trash = 0
            (xv, yv) = self._to_pixel_coords(xv, yv)
            # x is provided but y isn't
            (x, trash) = self._to_pixel_coords(x, trash)

            # Get the rotation angle and y-value
            x, y, dy_dx = BasePlot.get_x_y_dydx(xv, yv, x)
            rot = np.arctan(dy_dx) / np.pi * 180.

        elif x is None and y is not None:
            # y is provided, but x isn't
            _xv = xv[::-1]
            _yv = yv[::-1]
            # Find x by interpolation
            x = interpolate_values_1d(yv, xv, x_points=y)
            trash = 0
            (xv, yv) = self._to_pixel_coords(xv, yv)
            (x, trash) = self._to_pixel_coords(x, trash)

            # Get the rotation angle and y-value
            x, y, dy_dx = BasePlot.get_x_y_dydx(xv, yv, x)
            rot = np.arctan(dy_dx) / np.pi * 180.
        (x, y) = self._to_data_coords(x, y)
        return (x, y, rot)

    def inline_label(self, xv, yv, x=None, y=None):
        """
        This will give the coordinates and rotation required to align a label with
        a line on a plot in axis units.
        """
        dimx = self._system[self._x_index]
        xv = dimx.to_SI(xv)
        if x is not None: x = dimx.to_SI(x)
        dimy = self._system[self._y_index]
        yv = dimy.to_SI(yv)
        if y is not None: y = dimy.to_SI(y)
        (x, y, rot) = self._inline_label(xv, yv, x, y)
        x = dimx.from_SI(x)
        y = dimy.from_SI(y)
        return (x, y, rot)

    def plot_SI(self, _x, _y, *args, **kwargs):
        dimx = self._system[self._x_index]
        x = dimx.from_SI(_x)
        dimy = self._system[self._y_index]
        y = dimy.from_SI(_y)
        return self.axes.plot(x, y, *args, **kwargs)

    def show(self):
        plt.show()

    def savefig(self, *args, **kwargs):
        self.figure.savefig(*args, **kwargs)


if __name__ == "__main__":
    for sys in [SIunits(), KSIunits(), EURunits()]:
        print(sys.H.label)
        print(sys.H.to_SI(20))
        print(sys.P.label)
        print(sys.P.to_SI(20))

    # i_index, x_index, y_index, value=None, state=None)
    iso = IsoLine('T', 'H', 'P')
    print(iso.get_update_pair())

    state = AbstractState("HEOS", "water")
    iso = IsoLine('T', 'H', 'P', 300.0, state)
    hr = PropsSI("H", "T", [290, 310], "P", [1e5, 1e5], "water")
    pr = np.linspace(0.9e5, 1.1e5, 3)
    iso.calc_range(hr, pr)
    print(iso.x, iso.y)

    iso = IsoLine('Q', 'H', 'P', 0.0, state)
    iso.calc_range(hr, pr); print(iso.x, iso.y)
    iso = IsoLine('Q', 'H', 'P', 1.0, state)
    iso.calc_range(hr, pr); print(iso.x, iso.y)

    # bp = BasePlot(fluid_ref, graph_type, unit_system = 'KSI', **kwargs):
    bp = BasePlot('n-Pentane', 'PH', unit_system='EUR')
    # print(bp._get_sat_bounds('P'))
    # print(bp._get_iso_label(iso))
    print(bp.get_axis_limits())

        # get_update_pair(CoolProp.iP,CoolProp.iSmass,CoolProp.iT) -> (0,1,2,CoolProp.PSmass_INPUTS)
        # other values require switching and swapping
        # get_update_pair(CoolProp.iSmass,CoolProp.iP,CoolProp.iHmass) -> (1,0,2,CoolProp.PSmass_INPUTS)
