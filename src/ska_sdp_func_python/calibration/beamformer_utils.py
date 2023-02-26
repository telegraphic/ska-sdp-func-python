"""
Utilities to support rechannelisation of bandpass and delay solutions for CBF
beamformer calibration.
"""

import logging

import numpy
from numpy.polynomial import polynomial
from scipy import interpolate
from ska_sdp_datamodels.calibration.calibration_model import GainTable

log = logging.getLogger("func-python-logger")


def set_beamformer_frequencies(gain_table, array=None):
    """Generate a list of CBF beamformer frequencies

    SKA-Low beamformer:
     - Need Jones matrices for 384, 304 or 152 channels, per antenna, per beam
     - Station channels/beams are centred on integer multiples of 781.25 kHz
           781.25 kHz = 400 MHz / 512 channels
     - Station channels run from 50 MHz (64*df) to 350 MHz (448*df)
     - CBF beamformer calibration is done at the station channel resolution
     - Will assume that no padding is needed if input band < beamformer band

    MID beamformer
     - Need Jones matrices for 4096 channels, per antenna, per beam
     - Timing beam bandwidth : 200 MHz (channel width : 48.8281250 kHz?)
     - Search beam bandwidth : 300 MHz (channel width : 73.2421875 kHz?)
     - Set first beamformer channel centre frequency to first input channel

    :param gain_table: GainTable
    :param array: optional argument to explicitly set the array. Should be
         "LOW" or "MID". By default the gaintable configuration name will be
         used to set the array automatically.
    :return: numpy array of shape [nfreq,]
    """

    # determine array
    array_name = gain_table.configuration.name

    # initial gaintable frequencies
    frequency_gt = gain_table.frequency.data
    nfrequency_gt = len(frequency_gt)

    if nfrequency_gt <= 1:
        log.warning("Cannot rechannelise %d channel[s]", nfrequency_gt)
        return frequency_gt

    if array is None:
        if array_name.find("LOW") == 0:
            array = "LOW"
        elif array_name.find("MID") == 0:
            array = "MID"

    if array == "LOW":
        log.debug("Setting SKA-Low CBF beamformer frequencies")
        dfrequency_bf = 781.25e3
        starting_freq_bf = dfrequency_bf * numpy.round(
            numpy.amin(frequency_gt) / dfrequency_bf
        )
    elif array == "MID":
        log.debug("Setting SKA-Mid CBF beamformer frequencies")
        dfrequency_bf = 300.0e6 / 4096
        starting_freq_bf = numpy.amin(frequency_gt)
    else:
        log.warning("Unknown array: %s. Frequencies unchanged", array_name)
        return frequency_gt

    frequency_bf = numpy.arange(
        starting_freq_bf, numpy.amax(frequency_gt), dfrequency_bf
    )

    log.info("Setting bandpass calibration frequencies for %s CBF", array)
    log.info(" - %d input frequency channels", nfrequency_gt)
    log.info(
        " - input channel width: %.2f kHz, starting at %.2f MHz",
        (frequency_gt[1] - frequency_gt[0]) / 1e3,
        frequency_gt[0] / 1e6,
    )
    log.info(" - %d output frequency channels", len(frequency_bf))
    log.info(
        " - output channel width: %.2f kHz, starting at %.2f MHz",
        dfrequency_bf / 1e3,
        frequency_bf[0] / 1e6,
    )

    return frequency_bf


def expand_delay_phase(gain_table, frequency, reference_to_centre=True):
    """CASA delay calibration tables with type K or Kcross are currently stored
    in GainTable Jones matrices as phase shifts at a single reference
    frequency. These are expanded to other frequencies assuming
    phase = 2 * pi * t_delay * frequency.
    Note that this only works if the delay is less than half a wavelength at
    the reference frequency. In the future it is likely that the time delay
    will be stored in such GainTables and used directly.

    :param gain_table: GainTable with single phase values derived from
        delays. Must have jones_type "K".
    :param frequency: list of frequencies in Hz to generate phase shifts for
    :param reference_to_centre: if true (the default), shift the phases such
        that the phase shift at the input reference frequency is zero. This
        is done in CASA calibration tasks when delay solutions are given as
        prior calibration terms, so also needs to be done when combining delay
        with any subsequent calibration solutions.
    :return: GainTable array with len(frequency) phase values
    """
    if gain_table.jones_type != "K":
        raise ValueError(f"Wrong Jones type: {gain_table.jones_type} != K")
    # after extrapolating to other frequencies the Jones type will be set to B

    if gain_table.frequency.shape[0] != 1:
        raise ValueError("Expect a single frequency")
    frequency0 = gain_table.frequency.data[0]

    shape = numpy.array(gain_table.gain.shape)
    shape[2] = len(frequency)

    gain = numpy.empty(shape, "complex128")

    # Set the gain weight to one and residual to zero
    weight = numpy.ones(shape)
    residual = numpy.zeros((shape[0], shape[2], shape[3], shape[4]))

    # only works if the delay at ref freq is less than half a wavelength
    phase0 = numpy.angle(gain_table.gain.data)

    for chan, freq in enumerate(frequency):
        if reference_to_centre:
            freq -= frequency0
        gain[:, :, chan, :, :] = numpy.exp(
            1j * freq / frequency0 * phase0[:, :, 0, :, :]
        )

    return GainTable.constructor(
        gain=gain,
        time=gain_table.time,
        interval=gain_table.interval,
        weight=weight,
        residual=residual,
        frequency=frequency,
        receptor_frame=gain_table.receptor_frame1,
        phasecentre=gain_table.phasecentre,
        configuration=gain_table.configuration,
        jones_type="B",
    )


def _set_gaintable_product_shape(gain_table1, gain_table2, elementwise):
    """Determine the shape of the product of two GainTables

    :param gain_table1: GainTable containing left-hand side Jones matrices
    :param gain_table2: GainTable containing right-hand side Jones matrices
    :param elementwise: Do elementwise multiplication of calibration terms
    :return: Shape of the combined GainTable
    """
    gain1 = gain_table1.gain.data
    gain2 = gain_table2.gain.data

    if gain1.shape[0] != gain2.shape[0]:
        raise ValueError("time error {gain1.shape[0]} != {gain2.shape[0]}")
    if gain1.shape[1] != gain2.shape[1]:
        raise ValueError("antenna error {gain1.shape[1]} != {gain2.shape[1]}")
    # Tables must have the same number of channels, unless one set is constant
    # with a single Jones matrix per time and antenna
    if (
        gain1.shape[2] != gain2.shape[2]
        and gain1.shape[2] != 1
        and gain2.shape[2] != 1
    ):
        raise ValueError("frequency error {gain1.shape} != {gain2.shape}")
    if elementwise:
        if gain1.shape[3] != gain2.shape[3]:
            raise ValueError("pol error {gain1.shape[3]} != {gain2.shape[3]}")
        if gain1.shape[4] != gain2.shape[4]:
            raise ValueError("pol error {gain1.shape[4]} != {gain2.shape[4]}")
    else:
        # Make sure that ncol of matrix 1 equals nrow of matrix 2
        if gain_table1.receptor2.shape != gain_table2.receptor1.shape:
            raise ValueError("Matrices not compatible for multiplication")

    return (
        gain1.shape[0],
        gain1.shape[1],
        max(gain1.shape[2], gain2.shape[2]),
        gain1.shape[3],
        gain2.shape[4],
    )


def multiply_gaintable_jones(gain_table1, gain_table2, elementwise=False):
    """Multiply the Jones matrices for all times, antennas and frequencies
    of two GainTables.

    :param gain_table1: GainTable containing left-hand side Jones matrices
    :param gain_table2: GainTable containing right-hand side Jones matrices
    :param elementwise: Do elementwise multiplication of calibration terms.
        This is needed for gain tables that contain different factors of the
        same effect and need to be multiplied outside of the Jones formalism,
        such as D leakage terms and K cross-pol delays. Default is False.
    :return: GainTable containing gain_table1 Jones * gain_table2 Jones
    """
    if gain_table1.jones_type == "K" or gain_table2.jones_type == "K":
        raise ValueError("Cannot multiply delays. Use expand_delay_phase")

    shape = _set_gaintable_product_shape(gain_table1, gain_table2, elementwise)

    gain = numpy.empty(shape, "complex128")

    # Map output channel indices to input channel indices
    chan1 = numpy.arange(shape[2]).astype("int")
    chan2 = numpy.arange(shape[2]).astype("int")
    if gain_table1.gain.shape[2] == 1:
        chan1 *= 0
    if gain_table2.gain.shape[2] == 1:
        chan2 *= 0

    for time in range(0, shape[0]):
        for ant in range(0, shape[1]):
            for chan in range(0, shape[2]):
                if elementwise:
                    gain[time, ant, chan] = (
                        gain_table1.gain.data[time, ant, chan1[chan]]
                        * gain_table2.gain.data[time, ant, chan2[chan]]
                    )
                else:
                    gain[time, ant, chan] = (
                        gain_table1.gain.data[time, ant, chan1[chan]]
                        @ gain_table2.gain.data[time, ant, chan2[chan]]
                    )

    # Get the frequencies, noting that one set may be of length 1
    if gain_table1.gain.shape[2] > 1:
        frequency = gain_table1.frequency.data
        weight = gain_table1.weight
        residual = gain_table1.residual
    else:
        frequency = gain_table2.frequency.data
        weight = gain_table2.weight
        residual = gain_table2.residual

    # If the two tables have the same jones_type use that, otherwise use B.
    if gain_table1.jones_type == gain_table2.jones_type:
        jones_type = gain_table1.jones_type
    else:
        jones_type = "B"

    return GainTable.constructor(
        gain=gain,
        time=gain_table1.time,
        interval=gain_table1.interval,
        weight=weight,
        residual=residual,
        frequency=frequency,
        receptor_frame=gain_table1.receptor_frame1,
        phasecentre=gain_table1.phasecentre,
        configuration=gain_table1.configuration,
        jones_type=jones_type,
    )


def resample_bandpass(
    f_out, gain_table, alg="polyfit", edges=None, polydeg=None
):
    """Re-channelise each spectrum of gain or leakage terms

    algorithms:
     - polyfit  numpy.polynomial.polyval [default]
           polynomial fit to the real and imaginary part of each calibration
           parameter
     - cubicspl scipy.interpolate.CubicSpline
           cubic spline fit to the real and imaginary part of each calibration
           parameter
     - interp   numpy.interp
           binomial interpolation the real and imaginary part of each
           calibration parameter

    :param f_out: numpy array of shape [nfreq_out,]
    :param gain_table: GainTable
    :param alg: algorithm type [default polyfit]
    :param edges: list of edges (polyfit only) [default none]
    :param polydeg: degree of the fitting polynomial (polyfit only) [default 3]
    :return: numpy array of shape [nfreq_out,]
    """

    f_in = gain_table.frequency.data

    if alg == "polyfit":
        sel = PolynomialInterpolator()
        if edges is not None:
            sel.set_edges(edges)
        if polydeg is not None:
            sel.set_polydeg(polydeg)
    elif alg == "interp":
        sel = NumpyLinearInterpolator()
    elif alg == "cubicspl":
        sel = ScipySplineInterpolator()
    else:
        raise ValueError(f"unknown resampler {alg}")

    gain = gain_table.gain.data
    shape_out = numpy.array(gain.shape)
    shape_out[2] = len(f_out)
    gain_out = numpy.empty(shape_out, "complex128")
    for time in range(0, shape_out[0]):
        for ant in range(0, shape_out[1]):
            for rec1 in range(0, shape_out[3]):
                for rec2 in range(0, shape_out[4]):
                    gain_out[time, ant, :, rec1, rec2] = sel.interp(
                        f_out, f_in, gain[time, ant, :, rec1, rec2]
                    )
    return gain_out


class PolynomialInterpolator:
    """fit the data using the numpy polynomial polyfit function

    Attributes
    ----------
    edges : numpy array
        A vector containing the starting channels of any band intervals
        requiring separate fits. Defaults to the full band.
        Internally, full-band edge channels are appended: [0, ..., nchan].
    polydeg : int [default 3]
        Order of the polynomial fit

    Methods
    -------
    set_edges(edges):
        Provide the start channels of any sub-bands requiring separate fits

    set_polydeg(polydeg):
        Update the degree of the fitting polynomial

    interp(self, f_out, f_in, gain):
        Do the interpolation for the gain in "gain"

    """

    def __init__(self):
        self.edges = None
        self.polydeg = 3

    def set_edges(self, edges):
        """Provide the start channels of any sub-bands requiring separate fits

        :param edges: list of edges (starting channel indices)

        """
        self.edges = edges

    def set_polydeg(self, polydeg):
        """Update the order of the polynomial fit

        :param polydeg: Order of the polynomial fit

        """
        self.polydeg = polydeg

    def interp(self, f_out, f_in, gain):
        """Do the interpolation for the complex data in "gain"

        :param f_out: numpy array of shape [len(f_out)]
            final frequency values
        :param f_in: numpy array of shape [len(f_in)]
            initial frequency values
        :param gain: numpy array of shape [len(f_in)]
            complex sequence to interpolate
        :return: numpy array of shape [len(f_out)]
            interpolated complex sequence

        """
        if self.edges is None or self.edges == []:
            self.edges = numpy.array([0, len(f_in)])
            fstr = f"set edges to {self.edges}"
            log.debug("set edges to %s", fstr)
        # ensure that the channel before the first discontinuity are included
        if self.edges[0] > 0:
            self.edges = numpy.concatenate(([0], self.edges))
        # ensure that the channel after the last discontinuity are included
        if self.edges[-1] < len(f_in):
            self.edges = numpy.concatenate((self.edges, [len(f_in)]))

        idx_out = numpy.arange(0, len(f_out)).astype("int")
        gain_out = numpy.empty(len(f_out), "complex128")

        df_in = f_in[1] - f_in[0]
        edges = self.edges
        for k in range(0, len(edges) - 1):
            ch_in = numpy.arange(edges[k], edges[k + 1]).astype("int")
            ch_out = idx_out[
                (f_out >= f_in[edges[k]] - df_in / 2)
                * (f_out < f_in[edges[k + 1] - 1] + df_in / 2)
            ]

            # fit the data using polynomials
            coef_re = polynomial.polyfit(
                f_in[ch_in], numpy.real(gain[ch_in]), self.polydeg
            )
            coef_im = polynomial.polyfit(
                f_in[ch_in], numpy.imag(gain[ch_in]), self.polydeg
            )
            # evaluated the fits at the output frequencies
            gain_out[ch_out] = (
                polynomial.polyval(f_out[ch_out], coef_re)
                + polynomial.polyval(f_out[ch_out], coef_im) * 1j
            )

        return gain_out


# could add the extrapolation options instead of disabling the pylint
# error, or just remove this interpolator. It is pretty simple and fast.
class NumpyLinearInterpolator:  # pylint: disable=too-few-public-methods
    """fit the data using the numpy interp function

    Methods
    -------

    interp(self, f_out, f_in, gain):
        Do the interpolation for the gain in "gain"

    """

    def interp(self, f_out, f_in, gain):
        """Do the interpolation for the complex data in "gain"

        :param f_out: numpy array of shape [len(f_out)]
            final frequency values
        :param f_in: numpy array of shape [len(f_in)]
            initial frequency values
        :param gain: numpy array of shape [len(f_in)]
            complex sequence to interpolate
        :return: numpy array of shape [len(f_out)]
            interpolated complex sequence

        """
        return numpy.interp(f_out, f_in, gain)


# could add the extrapolation options instead of disabling the pylint
class ScipySplineInterpolator:  # pylint: disable=too-few-public-methods
    """fit the data using the scipy interpolate CubicSpline function

    Methods
    -------
    interp(self, f_out, f_in, gain):
        Do the interpolation for the gain in "gain"

    """

    def interp(self, f_out, f_in, gain):
        """Do the interpolation for the complex data in "gain"

        :param f_out: numpy array of shape [len(f_out)]
            final frequency values
        :param f_in: numpy array of shape [len(f_in)]
            initial frequency values
        :param gain: numpy array of shape [len(f_in)]
            complex sequence to interpolate
        :return: numpy array of shape [len(f_out)]
            interpolated complex sequence

        """
        func = interpolate.CubicSpline(f_in, gain)
        return func(f_out)
