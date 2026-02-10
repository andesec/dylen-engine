"""
Updated Mirascope helper functions with selective widget schemas.

This module demonstrates how to use selective schemas with Mirascope
to reduce token usage by only including relevant widgets.
"""

from mirascope.llm import gemini, prompt_template

from app.schema.selective_schema import create_selective_section, get_outcomes_section, get_section_builder_section

# Example 1: Outcomes agent (minimal - only markdown + mcqs)
OutcomesSection = get_outcomes_section()


@gemini.call(model="gemini-2.0-flash-exp", response_model=OutcomesSection)
@prompt_template(
  """
    Generate learning outcomes for: {topic}
    
    Create a section with:
    - Title describing the learning goals
    - Markdown overview of what students will learn
    - Subsections with markdown explanations and multiple-choice quizzes
    
    Use ONLY markdown and mcqs widgets.
    
    Topic: {topic}
    """
)
def generate_outcomes(topic: str): ...


# Example 2: Section builder agent (6 core widgets)
SectionBuilderSection = get_section_builder_section()


@gemini.call(model="gemini-2.0-flash-exp", response_model=SectionBuilderSection)
@prompt_template(
  """
    Generate an educational section about {topic}.
    
    The section should include:
    - A clear title
    - An introductory markdown explanation
    - 1-3 subsections with interactive widgets
    
    Available widgets: markdown, flipcards, translations, fill-in-blanks, tables, quizzes
    
    Topic: {topic}
    Difficulty: {difficulty}
    """
)
def generate_section(topic: str, difficulty: str = "intermediate"): ...


# Example 3: Custom widget selection
def generate_custom_section(topic: str, widget_types: list[str]):
  """
  Generate a section with custom widget selection.

  Args:
      topic: Topic to generate content for
      widget_types: List of widget names to allow (e.g., ['markdown', 'flipcards', 'table'])
  """
  # Create a custom Section class with only specified widgets
  custom_section = create_selective_section(widget_types)

  @gemini.call(model="gemini-2.0-flash-exp", response_model=custom_section)
  @prompt_template(
    """
        Generate an educational section about {topic}.
        
        Available widgets: {available_widgets}
        
        Topic: {topic}
        """
  )
  def _generate(topic: str, available_widgets: str): ...

  return _generate(topic=topic, available_widgets=", ".join(widget_types))


# Example usage:
if __name__ == "__main__":
  # Generate outcomes (minimal schema - only markdown + mcqs)
  outcomes = generate_outcomes(topic="Python Basics")
  print(f"Outcomes section: {outcomes.section}")
  print(f"Subsections: {len(outcomes.subsections)}")

  # Generate section with 6 widgets
  section = generate_section(topic="Machine Learning", difficulty="beginner")
  print(f"Section: {section.section}")

  # Generate with custom widgets
  custom = generate_custom_section(topic="Data Structures", widget_types=["markdown", "table", "codeEditor", "mcqs"])
  print(f"Custom section: {custom.section}")
