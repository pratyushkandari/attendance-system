import numpy as np
import pytest
import torch

from app.ai import facenet_model
from app.config import _env_flag
from app.extensions import db
from app.models.student import Student


@pytest.mark.parametrize("raw, expected", [
    ("1", True), ("true", True), (" Yes ", True), ("on", True),
    ("0", False), ("false", False), ("", False),
])
def test_env_flag_parses_common_spellings(monkeypatch, raw, expected):
    monkeypatch.setenv("VISIONATTEND_TEST_FLAG", raw)
    assert _env_flag("VISIONATTEND_TEST_FLAG") is expected


def test_env_flag_falls_back_to_the_default_when_unset(monkeypatch):
    monkeypatch.delenv("VISIONATTEND_TEST_FLAG", raising=False)
    assert _env_flag("VISIONATTEND_TEST_FLAG", default=True) is True


class FakeResnet:
    """Stands in for InceptionResnetV1 so these tests never download the weights."""

    def __init__(self, output=None, error=None):
        self.output, self.error, self.input = output, error, None

    def __call__(self, tensor):
        self.input = tensor
        if self.error:
            raise self.error
        return self.output


def test_embedding_is_unit_length_and_fed_facenet_sized_input(monkeypatch):
    fake = FakeResnet(output=torch.full((1, 512), 3.0))
    monkeypatch.setattr(facenet_model, "get_resnet", lambda: fake)

    embedding = facenet_model.get_embedding_from_crop(np.full((90, 70, 3), 255, dtype=np.uint8))

    assert embedding.shape == (512,)
    assert np.linalg.norm(embedding) == pytest.approx(1.0)
    # 160 x 160 RGB, pixels scaled to [-1, 1] as (value - 127.5) / 128
    assert tuple(fake.input.shape) == (1, 3, 160, 160)
    assert torch.allclose(fake.input, torch.full_like(fake.input, (255 - 127.5) / 128.0))


@pytest.mark.parametrize("crop", [None, np.zeros((0, 0, 3), dtype=np.uint8)])
def test_embedding_of_an_empty_crop_is_none(crop):
    assert facenet_model.get_embedding_from_crop(crop) is None


def test_embedding_errors_return_none(monkeypatch):
    monkeypatch.setattr(facenet_model, "get_resnet", lambda: FakeResnet(error=RuntimeError("boom")))
    assert facenet_model.get_embedding_from_crop(np.full((90, 70, 3), 128, dtype=np.uint8)) is None


def test_student_embedding_round_trip_and_roll_lookup(app):
    student = Student(roll="2026CSE001", first_name="Ada", last_name="Test", department="CSE",
                      year="2026", email="ada@univ.edu")
    assert student.get_embedding() is None
    student.set_embedding(None)
    assert student.embedding is None
    student.set_embedding([0.5] * 512)
    assert student.get_embedding() == [0.5] * 512

    db.session.add(student)
    db.session.commit()
    assert Student.find_by_roll("") is None
    assert Student.find_by_roll("2026cse001").roll == "2026CSE001"
