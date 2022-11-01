"""Unit tests for image iteration


"""
import logging
import os
import unittest

import numpy
from ska_sdp_datamodels.science_data_model.polarisation_model import PolarisationFrame

from src.ska_sdp_func_python.image.gather_scatter import (
    image_gather_facets,
    image_scatter_facets,
    image_gather_channels,
    image_scatter_channels,
)
from src.ska_sdp_func_python.image.operations import create_empty_image_like
from src.ska_sdp_func_python.simulation import create_test_image

log = logging.getLogger("rascil-logger")

log.setLevel(logging.WARNING)


class TestImageGatherScatters(unittest.TestCase):
    def setUp(self):
        from src.ska_sdp_func_python.parameters import rascil_path

        self.results_dir = rascil_path("test_results")
        self.persist = os.getenv("RASCIL_PERSIST", False)

    def test_scatter_gather_facet(self):

        m31original = create_test_image(polarisation_frame=PolarisationFrame("stokesI"))
        assert numpy.max(numpy.abs(m31original["pixels"].data)), "Original is empty"

        for nraster in [1, 4, 8]:
            m31model = create_test_image(
                polarisation_frame=PolarisationFrame("stokesI")
            )
            image_list = image_scatter_facets(m31model, facets=nraster)
            for patch in image_list:
                assert patch["pixels"].data.shape[3] == (
                    m31model["pixels"].data.shape[3] // nraster
                ), "Number of pixels in each patch: %d not as expected: %d" % (
                    patch["pixels"].data.shape[3],
                    (m31model["pixels"].data.shape[3] // nraster),
                )
                assert patch["pixels"].data.shape[2] == (
                    m31model["pixels"].data.shape[2] // nraster
                ), "Number of pixels in each patch: %d not as expected: %d" % (
                    patch["pixels"].data.shape[2],
                    (m31model["pixels"].data.shape[2] // nraster),
                )
                patch["pixels"].data[...] = 1.0
            m31reconstructed = create_empty_image_like(m31model)
            m31reconstructed = image_gather_facets(
                image_list, m31reconstructed, facets=nraster
            )
            flat = image_gather_facets(
                image_list, m31reconstructed, facets=nraster, return_flat=True
            )

            assert numpy.max(numpy.abs(flat["pixels"].data)), (
                "Flat is empty for %d" % nraster
            )
            assert numpy.max(numpy.abs(m31reconstructed["pixels"].data)), (
                "Raster is empty for %d" % nraster
            )

    def test_scatter_gather_facet_overlap(self):

        m31original = create_test_image(polarisation_frame=PolarisationFrame("stokesI"))
        assert numpy.max(numpy.abs(m31original["pixels"].data)), "Original is empty"

        for nraster, overlap in [(1, 0), (4, 8), (8, 16)]:
            m31model = create_test_image(
                polarisation_frame=PolarisationFrame("stokesI")
            )
            image_list = image_scatter_facets(m31model, facets=nraster, overlap=overlap)
            for patch in image_list:
                assert patch["pixels"].data.shape[3] == (
                    m31model["pixels"].data.shape[3] // nraster
                ), "Number of pixels in each patch: %d not as expected: %d" % (
                    patch["pixels"].data.shape[3],
                    (m31model["pixels"].data.shape[3] // nraster),
                )
                assert patch["pixels"].data.shape[2] == (
                    m31model["pixels"].data.shape[2] // nraster
                ), "Number of pixels in each patch: %d not as expected: %d" % (
                    patch["pixels"].data.shape[2],
                    (m31model["pixels"].data.shape[2] // nraster),
                )
                patch["pixels"].data[...] = 1.0
            m31reconstructed = create_empty_image_like(m31model)
            m31reconstructed = image_gather_facets(
                image_list, m31reconstructed, facets=nraster, overlap=overlap
            )
            flat = image_gather_facets(
                image_list,
                m31reconstructed,
                facets=nraster,
                overlap=overlap,
                return_flat=True,
            )

            assert numpy.max(numpy.abs(flat["pixels"].data)), (
                "Flat is empty for %d" % nraster
            )
            assert numpy.max(numpy.abs(m31reconstructed["pixels"].data)), (
                "Raster is empty for %d" % nraster
            )

    def test_scatter_gather_facet_overlap_taper(self):

        m31original = create_test_image(polarisation_frame=PolarisationFrame("stokesI"))
        assert numpy.max(numpy.abs(m31original["pixels"].data)), "Original is empty"

        for taper in ["linear", "tukey", None]:
            for nraster, overlap in [
                (1, 0),
                (2, 1),
                (2, 8),
                (4, 4),
                (4, 8),
                (8, 8),
                (8, 16),
            ]:
                m31model = create_test_image(
                    polarisation_frame=PolarisationFrame("stokesI")
                )
                image_list = image_scatter_facets(
                    m31model, facets=nraster, overlap=overlap, taper=taper
                )
                for patch in image_list:
                    assert patch["pixels"].data.shape[3] == (
                        m31model["pixels"].data.shape[3] // nraster
                    ), "Number of pixels in each patch: %d not as expected: %d" % (
                        patch.data.shape[3],
                        (m31model["pixels"].data.shape[3] // nraster),
                    )
                    assert patch["pixels"].data.shape[2] == (
                        m31model["pixels"].data.shape[2] // nraster
                    ), "Number of pixels in each patch: %d not as expected: %d" % (
                        patch.data.shape[2],
                        (m31model["pixels"].data.shape[2] // nraster),
                    )
                m31reconstructed = create_empty_image_like(m31model)
                m31reconstructed = image_gather_facets(
                    image_list,
                    m31reconstructed,
                    facets=nraster,
                    overlap=overlap,
                    taper=taper,
                )
                flat = image_gather_facets(
                    image_list,
                    m31reconstructed,
                    facets=nraster,
                    overlap=overlap,
                    taper=taper,
                    return_flat=True,
                )
                if self.persist:
                    m31reconstructed.image_acc.export_to_fits(
                        "%s/test_image_gather_scatter_%dnraster_%doverlap_%s_reconstructed.fits"
                        % (self.results_dir, nraster, overlap, taper),
                    )
                if self.persist:
                    flat.image_acc.export_to_fits(
                        "%s/test_image_gather_scatter_%dnraster_%doverlap_%s_flat.fits"
                        % (self.results_dir, nraster, overlap, taper),
                    )

                assert numpy.max(numpy.abs(flat["pixels"].data)), (
                    "Flat is empty for %d" % nraster
                )
                assert numpy.max(numpy.abs(m31reconstructed["pixels"].data)), (
                    "Raster is empty for %d" % nraster
                )

    def test_scatter_gather_channel(self):
        for nchan in [128, 16]:
            m31cube = create_test_image(
                frequency=numpy.linspace(1e8, 1.1e8, nchan),
                polarisation_frame=PolarisationFrame("stokesI"),
            )

            for subimages in [16, 8, 2, 1]:
                image_list = image_scatter_channels(m31cube, subimages=subimages)
                m31cuberec = image_gather_channels(
                    image_list, m31cube, subimages=subimages
                )
                diff = m31cube["pixels"].data - m31cuberec["pixels"].data
                assert numpy.max(numpy.abs(diff)) == 0.0, (
                    "Scatter gather failed for %d" % subimages
                )

    def test_gather_channel(self):
        for nchan in [128, 16]:
            m31cube = create_test_image(
                frequency=numpy.linspace(1e8, 1.1e8, nchan),
                polarisation_frame=PolarisationFrame("stokesI"),
            )
            image_list = image_scatter_channels(m31cube, subimages=nchan)
            m31cuberec = image_gather_channels(image_list, None, subimages=nchan)
            assert m31cube["pixels"].shape == m31cuberec["pixels"].shape
            diff = m31cube["pixels"].data - m31cuberec["pixels"].data
            assert numpy.max(numpy.abs(diff)) == 0.0, (
                "Scatter gather failed for %d" % nchan
            )


if __name__ == "__main__":
    unittest.main()