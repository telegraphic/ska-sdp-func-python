# pylint: disable=invalid-name, too-many-arguments, too-many-public-methods
# pylint: disable=attribute-defined-outside-init, unused-variable
# pylint: disable=too-many-instance-attributes, invalid-envvar-default
# pylint: disable=consider-using-f-string, logging-not-lazy
# pylint: disable=missing-class-docstring, missing-function-docstring
# pylint: disable=import-error, no-name-in-module, import-outside-toplevel
""" Unit tests for imaging using nifty gridder

"""
import pytest

pytestmark = pytest.skip(allow_module_level=True)
import logging
import os
import sys
import tempfile
import unittest

import numpy
from astropy import units as u
from astropy.coordinates import SkyCoord
from ska_sdp_datamodels.configuration.config_create import (
    create_named_configuration,
)
from ska_sdp_datamodels.science_data_model.polarisation_model import (
    PolarisationFrame,
)

from ska_sdp_func_python.imaging.dft import dft_skycomponent_visibility
from ska_sdp_func_python.skycomponent.operations import (
    find_nearest_skycomponent,
    find_skycomponents,
    insert_skycomponent,
)

# fix the below imports
from src.ska_sdp_func_python.image.operations import smooth_image
from src.ska_sdp_func_python.simulation import (
    create_unittest_components,
    create_unittest_model,
    ingest_unittest_visibility,
)

log = logging.getLogger("func-python-logger")

log.setLevel(logging.WARNING)
log.addHandler(logging.StreamHandler(sys.stdout))


class TestImagingNG(unittest.TestCase):
    def setUp(self):
        self.persist = os.getenv("FUNC_PYTHON_PERSIST", False)
        self.verbosity = 0

    def actualSetUp(
        self,
        freqwin=1,
        dospectral=True,
        image_pol=PolarisationFrame("stokesI"),
        zerow=False,
        mfs=False,
    ):

        self.npixel = 256
        self.low = create_named_configuration("LOWBD2", rmax=750.0)
        self.freqwin = freqwin
        self.vis = []
        self.ntimes = 5
        self.times = numpy.linspace(-3.0, +3.0, self.ntimes) * numpy.pi / 12.0

        if freqwin > 1:
            self.frequency = numpy.linspace(0.8e8, 1.2e8, self.freqwin)
            self.channelwidth = numpy.array(
                freqwin * [self.frequency[1] - self.frequency[0]]
            )
        else:
            self.frequency = numpy.array([1e8])
            self.channelwidth = numpy.array([1e6])

        if image_pol == PolarisationFrame("stokesIQUV"):
            self.vis_pol = PolarisationFrame("linear")
            self.image_pol = image_pol
            f = numpy.array([100.0, 20.0, -10.0, 1.0])
        elif image_pol == PolarisationFrame("stokesIQ"):
            self.vis_pol = PolarisationFrame("linearnp")
            self.image_pol = image_pol
            f = numpy.array([100.0, 20.0])
        elif image_pol == PolarisationFrame("stokesIV"):
            self.vis_pol = PolarisationFrame("circularnp")
            self.image_pol = image_pol
            f = numpy.array([100.0, 20.0])
        else:
            self.vis_pol = PolarisationFrame("stokesI")
            self.image_pol = PolarisationFrame("stokesI")
            f = numpy.array([100.0])

        if dospectral:
            flux = numpy.array(
                [f * numpy.power(freq / 1e8, -0.7) for freq in self.frequency]
            )
        else:
            flux = numpy.array([f])

        self.phasecentre = SkyCoord(
            ra=+180.0 * u.deg, dec=-45.0 * u.deg, frame="icrs", equinox="J2000"
        )
        self.vis = ingest_unittest_visibility(
            self.low,
            self.frequency,
            self.channelwidth,
            self.times,
            self.vis_pol,
            self.phasecentre,
            zerow=zerow,
        )

        self.model = create_unittest_model(
            self.vis, self.image_pol, npixel=self.npixel, nchan=freqwin
        )

        self.components = create_unittest_components(self.model, flux)

        self.model = insert_skycomponent(self.model, self.components)

        self.vis = dft_skycomponent_visibility(self.vis, self.components)

        # Calculate the model convolved with a Gaussian.

        self.cmodel = smooth_image(self.model)
        if self.persist:
            with tempfile.TemporaryDirectory() as tempdir:
                self.model.image_acc.export_to_fits(
                    f"{tempdir}/test_imaging_ng_model.fits"
                )
                self.cmodel.image_acc.export_to_fits(
                    f"{tempdir}/test_imaging_ng_cmodel.fits"
                )

        if mfs:
            self.model = create_unittest_model(
                self.vis, self.image_pol, npixel=self.npixel, nchan=1
            )

    def _checkcomponents(
        self, dirty, fluxthreshold=0.6, positionthreshold=0.1
    ):
        comps = find_skycomponents(
            dirty, fwhm=1.0, threshold=10 * fluxthreshold, npixels=5
        )
        assert len(comps) == len(self.components), (
            "Different number of components found: original %d, recovered %d"
            % (
                len(self.components),
                len(comps),
            )
        )
        cellsize = numpy.deg2rad(abs(dirty.image_acc.wcs.wcs.cdelt[0]))

        for comp in comps:
            # Check for agreement in direction
            ocomp, separation = find_nearest_skycomponent(
                comp.direction, self.components
            )
            if separation / cellsize > positionthreshold:
                raise ValueError(
                    "Component differs in position %.3f pixels"
                    % (separation / cellsize)
                )
            # Check that the polarisation values agree after normalisation
            numpy.testing.assert_array_almost_equal(
                ocomp.flux / ocomp.flux[0, 0],
                comp.flux / comp.flux[0, 0],
                err_msg=f"Original flux {ocomp.flux}, recovered flux {comp.flux}",
                decimal=6,
            )

    def _predict_base(self, fluxthreshold=1.0, name="predict_ng", **kwargs):

        from ska_sdp_func_python.imaging.ng import invert_ng, predict_ng

        original_vis = self.vis.copy(deep=True)
        vis = predict_ng(
            self.vis, self.model, verbosity=self.verbosity, **kwargs
        )
        vis["vis"].data = vis["vis"].data - original_vis["vis"].data
        dirty = invert_ng(
            vis,
            self.model,
            dopsf=False,
            normalise=True,
            verbosity=self.verbosity,
            **kwargs,
        )

        if self.persist:
            with tempfile.TemporaryDirectory() as tempdir:
                dirty[0].image_acc.export_to_fits(
                    f"{tempdir}/test_imaging_ng_{name}_residual.fits"
                )

        maxabs = numpy.max(numpy.abs(dirty[0]["pixels"].data))
        assert (
            maxabs < fluxthreshold
        ), "Error %.3f greater than fluxthreshold %.3f " % (
            maxabs,
            fluxthreshold,
        )

    def _invert_base(
        self,
        fluxthreshold=1.0,
        positionthreshold=1.0,
        check_components=True,
        name="predict_ng",
        **kwargs,
    ):

        # dirty = invert_ng(self.vis, self.model, dopsf=False, normalise=True, **kwargs)
        from ska_sdp_func_python.imaging.ng import invert_ng

        dirty = invert_ng(
            self.vis,
            self.model,
            normalise=True,
            verbosity=self.verbosity,
            **kwargs,
        )

        if self.persist:
            with tempfile.TemporaryDirectory() as tempdir:
                dirty[0].image_acc.export_to_fits(
                    f"{tempdir}/test_imaging_ng_{name}_dirty.fits"
                )
        assert numpy.max(numpy.abs(dirty[0]["pixels"].data)), "Image is empty"

        if check_components:
            self._checkcomponents(dirty[0], fluxthreshold, positionthreshold)

    def test_predict_ng(self):
        self.actualSetUp()
        self._predict_base(name="predict_ng")

    def test_predict_ng_IQUV(self):
        self.actualSetUp(image_pol=PolarisationFrame("stokesIQUV"))
        self._predict_base(name="predict_ng_IQUV")

    def test_predict_ng_IQ(self):
        self.actualSetUp(image_pol=PolarisationFrame("stokesIQ"))
        self._predict_base(name="predict_ng_IQ")

    def test_predict_ng_IV(self):
        self.actualSetUp(image_pol=PolarisationFrame("stokesIV"))
        self._predict_base(name="predict_ng_IV")

    def test_invert_ng(self):
        self.actualSetUp()
        self._invert_base(
            name="invert_ng", positionthreshold=2.0, check_components=True
        )

    def test_invert_ng_psf(self):
        self.actualSetUp()
        self._invert_base(
            name="invert_ng_psf",
            positionthreshold=2.0,
            check_components=False,
            dopsf=True,
        )

    def test_invert_ng_IQUV(self):
        self.actualSetUp(image_pol=PolarisationFrame("stokesIQUV"))
        self._invert_base(
            name="invert_ng_IQUV", positionthreshold=2.0, check_components=True
        )

    def test_invert_ng_IQUV_psf(self):
        self.actualSetUp(image_pol=PolarisationFrame("stokesIQUV"))
        self._invert_base(
            name="invert_ng_IQUV_psf",
            positionthreshold=2.0,
            check_components=False,
            dopsf=True,
        )

    def test_invert_ng_IQ(self):
        self.actualSetUp(image_pol=PolarisationFrame("stokesIQ"))
        self._invert_base(
            name="invert_ng_IQ", positionthreshold=2.0, check_components=True
        )

    def test_invert_ng_IV(self):
        self.actualSetUp(image_pol=PolarisationFrame("stokesIV"))
        self._invert_base(
            name="invert_ng_IV", positionthreshold=2.0, check_components=True
        )

    def test_predict_ng_spec(self):
        self.actualSetUp(dospectral=True, freqwin=5)
        self._predict_base(name="predict_spec")

    def test_invert_ng_spec(self):
        self.actualSetUp(dospectral=True, freqwin=5)
        self._invert_base(
            name="invert_spec", positionthreshold=2.0, check_components=False
        )

    def test_invert_ng_spec_psf(self):
        self.actualSetUp(dospectral=True, freqwin=5)
        self._invert_base(
            name="invert_spec_psf",
            positionthreshold=2.0,
            check_components=False,
            dopsf=True,
        )

    def test_predict_ng_spec_IQUV(self):
        self.actualSetUp(
            dospectral=True,
            freqwin=5,
            image_pol=PolarisationFrame("stokesIQUV"),
        )
        self._predict_base(name="predict_spec_IQUV")

    def test_invert_ng_spec_IQUV(self):
        self.actualSetUp(
            dospectral=True,
            freqwin=5,
            image_pol=PolarisationFrame("stokesIQUV"),
        )
        self._invert_base(
            name="invert_spec_IQUV",
            positionthreshold=2.0,
            check_components=False,
        )

    def test_invert_ng_spec_IQUV_psf(self):
        self.actualSetUp(
            dospectral=True,
            freqwin=5,
            image_pol=PolarisationFrame("stokesIQUV"),
        )
        self._invert_base(
            name="invert_spec_IQUV_psf",
            positionthreshold=2.0,
            check_components=False,
            dopsf=True,
        )

    def test_invert_ng_mfs_IQUV(self):
        self.actualSetUp(
            dospectral=True,
            freqwin=5,
            image_pol=PolarisationFrame("stokesIQUV"),
            mfs=True,
        )
        self._invert_base(
            name="invert_mfs_IQUV",
            positionthreshold=2.0,
            check_components=False,
        )

    def test_invert_ng_mfs_IQUV_psf(self):
        self.actualSetUp(
            dospectral=True,
            freqwin=5,
            image_pol=PolarisationFrame("stokesIQUV"),
            mfs=True,
        )
        self._invert_base(
            name="invert_mfs_IQUV_psf",
            positionthreshold=2.0,
            check_components=False,
            dopsf=True,
        )

    def test_predict_ng_spec_IQ(self):
        self.actualSetUp(
            dospectral=True, freqwin=5, image_pol=PolarisationFrame("stokesIQ")
        )
        self._predict_base(name="predict_spec_IQ")

    def test_invert_ng_spec_IQ(self):
        self.actualSetUp(
            dospectral=True, freqwin=5, image_pol=PolarisationFrame("stokesIQ")
        )
        self._invert_base(
            name="invert_spec_IQ",
            positionthreshold=2.0,
            check_components=False,
        )


if __name__ == "__main__":
    unittest.main()
