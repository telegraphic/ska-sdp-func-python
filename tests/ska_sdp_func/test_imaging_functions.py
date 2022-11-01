# pylint: disable=invalid-name, too-many-arguments, unused-argument
# pylint: disable=attribute-defined-outside-init, unused-variable
# pylint: disable=too-many-instance-attributes, invalid-envvar-default
# pylint: disable=consider-using-f-string, logging-not-lazy
# pylint: disable=missing-class-docstring, missing-function-docstring
# pylint: disable=import-error, no-name-in-module, import-outside-toplevel
""" Unit tests for Fourier transform processors


"""
import logging
import sys
import unittest

import numpy
from astropy import units as u
from astropy.coordinates import SkyCoord
from ska_sdp_datamodels.science_data_model.polarisation_model import (
    PolarisationFrame,
)

from src.ska_sdp_func_python.imaging.base import create_image_from_visibility
from src.ska_sdp_func_python.simulation import (
    create_named_configuration,
    create_unittest_model,
    ingest_unittest_visibility,
)

log = logging.getLogger("rascil-logger")

log.setLevel(logging.WARNING)
log.addHandler(logging.StreamHandler(sys.stdout))


class TestImagingFunctions(unittest.TestCase):
    def setUp(self):
        from src.ska_sdp_func_python.parameters import rascil_path

        self.results_dir = rascil_path("test_results")

    def actualSetUp(
        self, add_errors=False, freqwin=1, dospectral=True, dopol=False
    ):

        self.npixel = 256
        self.low = create_named_configuration("LOWBD2", rmax=750.0)
        self.freqwin = freqwin
        self.vis_list = []
        self.ntimes = 5
        self.times = numpy.linspace(-3.0, +3.0, self.ntimes) * numpy.pi / 12.0
        self.frequency = numpy.linspace(0.8e8, 1.2e8, self.freqwin)
        if freqwin > 1:
            self.channelwidth = numpy.array(
                freqwin * [self.frequency[1] - self.frequency[0]]
            )
        else:
            self.channelwidth = numpy.array([1e6])

        if dopol:
            self.vis_pol = PolarisationFrame("linear")
            self.image_pol = PolarisationFrame("stokesIQUV")

        else:
            self.vis_pol = PolarisationFrame("stokesI")
            self.image_pol = PolarisationFrame("stokesI")

        self.phasecentre = SkyCoord(
            ra=+180.0 * u.deg, dec=-60.0 * u.deg, frame="icrs", equinox="J2000"
        )
        self.vis = ingest_unittest_visibility(
            config=self.low,
            frequency=self.frequency,
            channel_bandwidth=self.channelwidth,
            times=self.times,
            phasecentre=self.phasecentre,
            vis_pol=self.vis_pol,
        )

        self.model = create_unittest_model(
            self.vis, self.image_pol, npixel=self.npixel
        )

    def test_create_image_from_visibility(self):
        self.actualSetUp()
        im = create_image_from_visibility(self.vis, nchan=1, npixel=128)
        assert im["pixels"].data.shape == (1, 1, 128, 128)
        im = create_image_from_visibility(
            self.vis, frequency=self.frequency, npixel=128
        )
        assert im["pixels"].data.shape == (len(self.frequency), 1, 128, 128)
        im = create_image_from_visibility(
            self.vis, frequency=self.frequency, npixel=128, nchan=1
        )
        assert im["pixels"].data.shape == (1, 1, 128, 128)


if __name__ == "__main__":
    unittest.main()
