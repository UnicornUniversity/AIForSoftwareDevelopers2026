"""Concrete adapters for real video files, models, services and hardware.

Every adapter implements a Protocol from :mod:`drone_vision_lab.interfaces` and
is constructed only by the composition root (:mod:`drone_vision_lab.container`)
or by a UI workflow that receives a factory from it.
"""

from .video import FileVideoSource, make_video_source

__all__ = ["FileVideoSource", "make_video_source"]
