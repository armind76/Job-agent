"""Structured resume data model."""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ExperienceItem:
    company: str
    title: str
    dates: str
    location: str = ""
    bullets: list[str] = field(default_factory=list)


@dataclass
class ProjectItem:
    name: str
    bullets: list[str] = field(default_factory=list)
    technologies: list[str] = field(default_factory=list)
    url: str = ""
    description: str = ""  # one-line summary for Claude to reason about


@dataclass
class EducationItem:
    institution: str
    degree: str
    dates: str = ""
    details: list[str] = field(default_factory=list)


@dataclass
class ResumeData:
    # Contact / header
    name: str = ""
    email: str = ""
    phone: str = ""
    location: str = ""
    linkedin: str = ""
    github: str = ""
    portfolio: str = ""

    # Body sections  (experience + education are NEVER modified)
    summary: str = ""
    skills: list[str] = field(default_factory=list)        # full pool
    experience: list[ExperienceItem] = field(default_factory=list)
    projects: list[ProjectItem] = field(default_factory=list)   # full pool
    education: list[EducationItem] = field(default_factory=list)
