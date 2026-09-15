"""
Relational Entities for Outbound Pipeline Web Application.
Maps domain concepts: User, Profile, Resume, Campaign, Company, Person,
Contact, PipelineRun, Draft, Review, Delivery, PipelineEvent, and RevokedToken.
"""
import uuid
from datetime import datetime, timezone
from typing import Optional, List
from sqlalchemy import (
    String, Text, Boolean, Integer, Float, DateTime, ForeignKey, Index
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from server.models.base import Base


def generate_uuid() -> str:
    return str(uuid.uuid4())


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    # Relationships
    profile: Mapped[Optional["Profile"]] = relationship("Profile", back_populates="user", uselist=False, cascade="all, delete-orphan")
    resumes: Mapped[List["Resume"]] = relationship("Resume", back_populates="user", cascade="all, delete-orphan")
    campaigns: Mapped[List["Campaign"]] = relationship("Campaign", back_populates="user", cascade="all, delete-orphan")


class Profile(Base):
    __tablename__ = "profiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    location: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    github_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    portfolio_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    linkedin_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    custom_instructions: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    work_preferences_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    user: Mapped["User"] = relationship("User", back_populates="profile")


class Resume(Base):
    __tablename__ = "resumes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str] = mapped_column(String(512), nullable=False)
    parsed_data_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    parsing_status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)  # pending, completed, failed
    parsing_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    user: Mapped["User"] = relationship("User", back_populates="resumes")
    campaigns: Mapped[List["Campaign"]] = relationship("Campaign", back_populates="resume")


class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    resume_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("resumes.id", ondelete="SET NULL"), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    target_geography: Mapped[str] = mapped_column(String(128), default="India", nullable=False)
    industry: Mapped[str] = mapped_column(String(128), default="Cybersecurity", nullable=False)
    company_size: Mapped[str] = mapped_column(String(64), default="small", nullable=False)  # small, established, any
    company_stage: Mapped[str] = mapped_column(String(128), default="Seed / Early-Stage", nullable=False)
    target_roles_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    technologies_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    employment_type: Mapped[str] = mapped_column(String(64), default="full_time", nullable=False)
    remote_preference: Mapped[str] = mapped_column(String(64), default="any", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False)  # draft, active, completed, paused
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    user: Mapped["User"] = relationship("User", back_populates="campaigns")
    resume: Mapped[Optional["Resume"]] = relationship("Resume", back_populates="campaigns")
    companies: Mapped[List["Company"]] = relationship("Company", back_populates="campaign", cascade="all, delete-orphan")
    runs: Mapped[List["PipelineRun"]] = relationship("PipelineRun", back_populates="campaign", cascade="all, delete-orphan")
    events: Mapped[List["PipelineEvent"]] = relationship("PipelineEvent", back_populates="campaign", cascade="all, delete-orphan")


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    campaign_id: Mapped[str] = mapped_column(String(36), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False, index=True)
    domain: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    location: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    industry: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    stage: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    size: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    match_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    why_match_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    technical_signals_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sources_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    selection_status: Mapped[str] = mapped_column(String(32), default="discovered", nullable=False)  # discovered, selected, rejected, contacted
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    campaign: Mapped["Campaign"] = relationship("Campaign", back_populates="companies")
    person: Mapped[Optional["Person"]] = relationship("Person", back_populates="company", uselist=False, cascade="all, delete-orphan")
    contacts: Mapped[List["Contact"]] = relationship("Contact", back_populates="company", cascade="all, delete-orphan")
    runs: Mapped[List["PipelineRun"]] = relationship("PipelineRun", back_populates="company", cascade="all, delete-orphan")
    drafts: Mapped[List["Draft"]] = relationship("Draft", back_populates="company", cascade="all, delete-orphan")
    deliveries: Mapped[List["Delivery"]] = relationship("Delivery", back_populates="company", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_companies_campaign_domain", "campaign_id", "domain"),
    )


class Person(Base):
    __tablename__ = "persons"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    company_id: Mapped[str] = mapped_column(String(36), ForeignKey("companies.id", ondelete="CASCADE"), unique=True, nullable=False)
    first_name: Mapped[str] = mapped_column(String(128), nullable=False)
    last_name: Mapped[str] = mapped_column(String(128), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(255), nullable=False)
    linkedin_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    source_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    evidence_snippet: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    person_confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    grounding_sources_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    researched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    company: Mapped["Company"] = relationship("Company", back_populates="person")
    contacts: Mapped[List["Contact"]] = relationship("Contact", back_populates="person")


class Contact(Base):
    __tablename__ = "contacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    person_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("persons.id", ondelete="SET NULL"), nullable=True)
    company_id: Mapped[str] = mapped_column(String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), index=True, nullable=True)
    email_confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    verification_status: Mapped[str] = mapped_column(String(32), default="unverified", nullable=False)  # valid, accept_all, invalid, unverified
    provider: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    sources_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    raw_verification_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    resolved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    company: Mapped["Company"] = relationship("Company", back_populates="contacts")
    person: Mapped[Optional["Person"]] = relationship("Person", back_populates="contacts")
    drafts: Mapped[List["Draft"]] = relationship("Draft", back_populates="contact")
    deliveries: Mapped[List["Delivery"]] = relationship("Delivery", back_populates="contact")


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    campaign_id: Mapped[str] = mapped_column(String(36), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False, index=True)
    company_id: Mapped[str] = mapped_column(String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), default="queued", nullable=False, index=True)  # queued, running, waiting_for_review, completed, failed, skipped, cancelled
    last_completed_stage: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)  # discovery_completed, person_verified, email_resolved, draft_generated
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    campaign: Mapped["Campaign"] = relationship("Campaign", back_populates="runs")
    company: Mapped["Company"] = relationship("Company", back_populates="runs")
    draft: Mapped[Optional["Draft"]] = relationship("Draft", back_populates="pipeline_run", uselist=False, cascade="all, delete-orphan")
    review: Mapped[Optional["Review"]] = relationship("Review", back_populates="pipeline_run", uselist=False, cascade="all, delete-orphan")
    delivery: Mapped[Optional["Delivery"]] = relationship("Delivery", back_populates="pipeline_run", uselist=False, cascade="all, delete-orphan")
    events: Mapped[List["PipelineEvent"]] = relationship("PipelineEvent", back_populates="pipeline_run", cascade="all, delete-orphan")


class Draft(Base):
    __tablename__ = "drafts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    pipeline_run_id: Mapped[str] = mapped_column(String(36), ForeignKey("pipeline_runs.id", ondelete="CASCADE"), unique=True, nullable=False)
    company_id: Mapped[str] = mapped_column(String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    contact_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    persona: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)  # security, ai_ml, hr_talent
    raw_prompt_context_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    pipeline_run: Mapped["PipelineRun"] = relationship("PipelineRun", back_populates="draft")
    company: Mapped["Company"] = relationship("Company", back_populates="drafts")
    contact: Mapped[Optional["Contact"]] = relationship("Contact", back_populates="drafts")
    review: Mapped[Optional["Review"]] = relationship("Review", back_populates="draft", uselist=False, cascade="all, delete-orphan")


class Review(Base):
    __tablename__ = "reviews"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    pipeline_run_id: Mapped[str] = mapped_column(String(36), ForeignKey("pipeline_runs.id", ondelete="CASCADE"), unique=True, nullable=False)
    draft_id: Mapped[str] = mapped_column(String(36), ForeignKey("drafts.id", ondelete="CASCADE"), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False, index=True)  # pending, approved, edited, skipped
    edited_subject: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    edited_body: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reviewer_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    pipeline_run: Mapped["PipelineRun"] = relationship("PipelineRun", back_populates="review")
    draft: Mapped["Draft"] = relationship("Draft", back_populates="review")


class Delivery(Base):
    __tablename__ = "deliveries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    pipeline_run_id: Mapped[str] = mapped_column(String(36), ForeignKey("pipeline_runs.id", ondelete="CASCADE"), unique=True, nullable=False)
    company_id: Mapped[str] = mapped_column(String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    contact_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True)
    delivery_mode: Mapped[str] = mapped_column(String(32), default="staged", nullable=False)  # stub, staged, live
    delivery_status: Mapped[str] = mapped_column(String(32), nullable=False)  # staged, sent, failed, blocked_safety
    provider: Mapped[str] = mapped_column(String(64), default="instantly", nullable=False)
    staged_file_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    webhook_response_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    safety_audit_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    delivered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    pipeline_run: Mapped["PipelineRun"] = relationship("PipelineRun", back_populates="delivery")
    company: Mapped["Company"] = relationship("Company", back_populates="deliveries")
    contact: Mapped[Optional["Contact"]] = relationship("Contact", back_populates="deliveries")


class PipelineEvent(Base):
    __tablename__ = "pipeline_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    pipeline_run_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("pipeline_runs.id", ondelete="CASCADE"), nullable=True, index=True)
    campaign_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)  # discovery, leader_found, email_resolved, etc.
    message: Mapped[str] = mapped_column(Text, nullable=False)
    data_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False, index=True)

    pipeline_run: Mapped[Optional["PipelineRun"]] = relationship("PipelineRun", back_populates="events")
    campaign: Mapped[Optional["Campaign"]] = relationship("Campaign", back_populates="events")


class RevokedToken(Base):
    __tablename__ = "revoked_tokens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    jti: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    revoked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
