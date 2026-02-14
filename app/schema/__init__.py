"""Schema package exports."""

from .validate_lesson import validate_lesson
from .widget_models import LessonDocument, Section, Subsection, WidgetItem
from .widgets_loader import WidgetDefinition, WidgetRegistry, load_widget_registry

__all__ = ["LessonDocument", "Section", "Subsection", "WidgetItem", "validate_lesson", "WidgetDefinition", "WidgetRegistry", "load_widget_registry"]
