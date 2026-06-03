#!/usr/bin/env python3
"""
Generate a synthetic DICOM file for testing.

This script creates a valid single-frame DICOM file with:
- file meta information
- patient/study metadata
- grayscale pixel data

Examples:
  python generate_sample_dicom.py
  python generate_sample_dicom.py --output test.dcm --rows 512 --cols 512
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import numpy as np
from pydicom.dataset import Dataset, FileDataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, generate_uid


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate a synthetic DICOM file")
    parser.add_argument("-o", "--output", default="sample.dcm", help="Output DICOM file path")
    parser.add_argument("--rows", type=int, default=256, help="Image rows")
    parser.add_argument("--cols", type=int, default=256, help="Image columns")
    parser.add_argument("--patient-name", default="TEST^PATIENT", help="PatientName value")
    parser.add_argument("--patient-id", default="TEST001", help="PatientID value")
    parser.add_argument("--modality", default="OT", help="Modality value")
    parser.add_argument("--study-description", default="Synthetic DICOM Test", help="StudyDescription value")
    parser.add_argument("--series-description", default="Synthetic Series", help="SeriesDescription value")
    parser.add_argument("--photometric-interpretation", default="MONOCHROME2", help="PhotometricInterpretation value")
    return parser


def create_pixel_array(rows: int, cols: int) -> np.ndarray:
    """Create a simple phantom with gradients and a bright center circle."""
    y, x = np.ogrid[:rows, :cols]
    center_y = rows / 2.0
    center_x = cols / 2.0
    radius = min(rows, cols) / 4.0

    gradient = ((x / max(cols - 1, 1)) * 180 + (y / max(rows - 1, 1)) * 60).astype(np.float32)
    circle = ((x - center_x) ** 2 + (y - center_y) ** 2) <= radius ** 2
    gradient[circle] = 255

    return np.clip(gradient, 0, 255).astype(np.uint8)


def build_dataset(args: argparse.Namespace) -> FileDataset:
    output_path = Path(args.output)

    file_meta = FileMetaDataset()
    file_meta.FileMetaInformationVersion = b"\x00\x01"
    file_meta.MediaStorageSOPClassUID = generate_uid()
    file_meta.MediaStorageSOPInstanceUID = generate_uid()
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    file_meta.ImplementationClassUID = generate_uid()

    now = datetime.now()
    dataset = FileDataset(
        str(output_path),
        {},
        file_meta=file_meta,
        preamble=b"\x00" * 128,
    )

    dataset.is_little_endian = True
    dataset.is_implicit_VR = False

    dataset.SOPClassUID = file_meta.MediaStorageSOPClassUID
    dataset.SOPInstanceUID = file_meta.MediaStorageSOPInstanceUID
    dataset.StudyInstanceUID = generate_uid()
    dataset.SeriesInstanceUID = generate_uid()
    dataset.FrameOfReferenceUID = generate_uid()

    dataset.PatientName = args.patient_name
    dataset.PatientID = args.patient_id
    dataset.PatientBirthDate = "19700101"
    dataset.PatientSex = "O"
    dataset.StudyDate = now.strftime("%Y%m%d")
    dataset.StudyTime = now.strftime("%H%M%S")
    dataset.AccessionNumber = "TEST0001"
    dataset.Modality = args.modality
    dataset.Manufacturer = "Copilot Synthetic Generator"
    dataset.StudyDescription = args.study_description
    dataset.SeriesDescription = args.series_description
    dataset.InstitutionName = "Test Hospital"
    dataset.ReferringPhysicianName = "TEST^DOCTOR"

    dataset.SamplesPerPixel = 1
    dataset.PhotometricInterpretation = args.photometric_interpretation
    dataset.Rows = args.rows
    dataset.Columns = args.cols
    dataset.BitsAllocated = 8
    dataset.BitsStored = 8
    dataset.HighBit = 7
    dataset.PixelRepresentation = 0
    dataset.PlanarConfiguration = 0
    dataset.ImagesInAcquisition = 1
    dataset.InstanceNumber = 1

    pixel_array = create_pixel_array(args.rows, args.cols)
    dataset.PixelData = pixel_array.tobytes()

    dataset.ContentDate = now.strftime("%Y%m%d")
    dataset.ContentTime = now.strftime("%H%M%S")

    # Add a few optional tags that are useful in viewers/debugging
    dataset.WindowCenter = 128
    dataset.WindowWidth = 256
    dataset.RescaleIntercept = 0
    dataset.RescaleSlope = 1

    return dataset


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    dataset = build_dataset(args)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    dataset.save_as(str(output_path), write_like_original=False)

    print(f"Created synthetic DICOM: {output_path.resolve()}")
    print(f"Size: {dataset.Rows} x {dataset.Columns}")
    print(f"Patient: {dataset.PatientName} ({dataset.PatientID})")
    print(f"Modality: {dataset.Modality}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())