"""
Unit Tests for Server Domain Models, SQLite WAL Configuration, and Relationships.
Validates Phase 1 database entities and state checkpointing fields.
"""
import pytest
from datetime import datetime, timezone, timedelta
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from server.models.base import Base
from server.database import create_db_engine
from server.models.entities import (
    User,
    Profile,
    Resume,
    Campaign,
    Company,
    Person,
    Contact,
    PipelineRun,
    Draft,
    Review,
    Delivery,
    PipelineEvent,
    RevokedToken,
)


@pytest.fixture
def db_session(tmp_path):
    """Creates a temporary isolated SQLite database with full WAL pragmas for testing."""
    test_db_file = tmp_path / "test_outbound.db"
    test_db_url = f"sqlite:///{test_db_file}"
    engine = create_db_engine(db_url=test_db_url)
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_sqlite_pragmas_enabled(db_session):
    """Verifies that SQLite connections enable WAL mode, foreign keys, and busy timeout."""
    connection = db_session.connection().connection

    cursor = connection.cursor()
    cursor.execute("PRAGMA foreign_keys;")
    foreign_keys = cursor.fetchone()[0]
    assert foreign_keys == 1, "Foreign keys must be enabled in SQLite"

    cursor.execute("PRAGMA journal_mode;")
    journal_mode = cursor.fetchone()[0]
    assert journal_mode.lower() == "wal", "SQLite must operate in WAL mode"

    cursor.execute("PRAGMA busy_timeout;")
    busy_timeout = cursor.fetchone()[0]
    assert busy_timeout >= 5000, "Busy timeout must be at least 5000ms"
    cursor.close()


def test_user_and_profile_lifecycle(db_session):
    """Verifies User creation, 1:1 Profile association, and cascading deletion."""
    user = User(
        email="operator@raghavpathak.me",
        password_hash="$2b$12$e8YkZ...",
        is_active=True
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    assert user.id is not None
    assert user.email == "operator@raghavpathak.me"

    profile = Profile(
        user_id=user.id,
        full_name="Raghav Pathak",
        title="Security & AI Engineer",
        email="raghav.candidate.outreach@example.com",
        location="Jaipur / Noida, India",
        github_url="https://github.com/raghavpathak30",
        portfolio_url="https://raghavpathak.dev",
        linkedin_url="https://linkedin.com/in/raghav-pathak",
        custom_instructions="Focus on homomorphic encryption and LLM guardrails."
    )
    db_session.add(profile)
    db_session.commit()
    db_session.refresh(user)

    assert user.profile is not None
    assert user.profile.full_name == "Raghav Pathak"
    assert user.profile.portfolio_url == "https://raghavpathak.dev"

    # Verify cascading delete
    db_session.delete(user)
    db_session.commit()

    deleted_profile = db_session.execute(select(Profile).where(Profile.id == profile.id)).scalar_one_or_none()
    assert deleted_profile is None, "Profile must be deleted when owning User is deleted"


def test_resume_entity_with_parsing_status_fields(db_session):
    """Verifies Resume entity supports parsing_status, parsing_error, and parsed_data_json upfront."""
    user = User(email="test_resume@raghavpathak.me", password_hash="hash")
    db_session.add(user)
    db_session.commit()

    # Initial upload: status is pending
    resume = Resume(
        user_id=user.id,
        filename="Raghav_Pathak_Security.pdf",
        file_path="uploads/resumes/uuid123.pdf",
        parsing_status="pending",
        is_active=True
    )
    db_session.add(resume)
    db_session.commit()
    db_session.refresh(resume)

    assert resume.parsing_status == "pending"
    assert resume.parsing_error is None
    assert resume.parsed_data_json is None

    # Simulate parsing completion
    resume.parsing_status = "completed"
    resume.parsed_data_json = '{"security_infrastructure": {"summary": "Specialist in applied crypto"}}'
    db_session.commit()
    db_session.refresh(resume)

    assert resume.parsing_status == "completed"
    assert "applied crypto" in resume.parsed_data_json


def test_campaign_company_and_ranking_flow(db_session):
    """Verifies Campaign definition, Company discovery records, match scores, and selection filtering."""
    user = User(email="campaign_user@raghavpathak.me", password_hash="hash")
    db_session.add(user)
    db_session.commit()

    campaign = Campaign(
        user_id=user.id,
        name="Indian Cybersecurity Startups",
        objective="Find early-stage cybersecurity startups in India for security engineering roles.",
        target_geography="India",
        industry="Cybersecurity",
        company_size="small",
        company_stage="Seed / Early-Stage",
        status="active"
    )
    db_session.add(campaign)
    db_session.commit()

    comp1 = Company(
        campaign_id=campaign.id,
        domain="shield-crypto.in",
        company_name="ShieldCrypto Technologies",
        location="Bengaluru, India",
        industry="Applied Cryptography",
        stage="Seed",
        size=7,
        match_score=94,
        why_match_json='["Focus on ZK proofs", "Early-stage Seed in India"]',
        selection_status="selected"
    )
    comp2 = Company(
        campaign_id=campaign.id,
        domain="irrelevant-retail.com",
        company_name="Irrelevant Retail",
        location="USA",
        industry="E-Commerce",
        stage="Series C",
        size=150,
        match_score=35,
        selection_status="rejected"
    )
    db_session.add_all([comp1, comp2])
    db_session.commit()

    # Query only selected companies with match_score >= 80
    selected_companies = db_session.execute(
        select(Company).where(
            Company.campaign_id == campaign.id,
            Company.selection_status == "selected",
            Company.match_score >= 80
        )
    ).scalars().all()

    assert len(selected_companies) == 1
    assert selected_companies[0].domain == "shield-crypto.in"
    assert selected_companies[0].match_score == 94


def test_two_stage_enrichment_entities(db_session):
    """Verifies Person (Stage 1 leader) and Contact (Stage 2 deliverability) records linked to Company."""
    user = User(email="enrich_user@raghavpathak.me", password_hash="hash")
    campaign = Campaign(user=user, name="Crypto Outreach", objective="Outreach")
    company = Company(campaign=campaign, domain="apex-vault.io", company_name="Apex Vault")
    db_session.add_all([user, campaign, company])
    db_session.commit()

    # Stage 1: Person Identification
    person = Person(
        company_id=company.id,
        first_name="Devon",
        last_name="Sterling",
        full_name="Devon Sterling",
        role="Chief Information Security Officer & VP Infrastructure",
        linkedin_url="https://linkedin.com/in/devon-sterling",
        source_url="https://apex-vault.io/leadership",
        evidence_snippet="Leading security engineering and infrastructure at Apex Vault.",
        person_confidence=0.95
    )
    db_session.add(person)
    db_session.commit()

    # Stage 2: Contact Resolution
    contact = Contact(
        person_id=person.id,
        company_id=company.id,
        email="devon.sterling@apex-vault.io",
        email_confidence=0.95,
        verification_status="valid",
        provider="hunter",
        sources_count=3
    )
    db_session.add(contact)
    db_session.commit()

    db_session.refresh(company)
    assert company.person is not None
    assert company.person.full_name == "Devon Sterling"
    assert company.person.person_confidence >= 0.70

    assert len(company.contacts) == 1
    assert company.contacts[0].email == "devon.sterling@apex-vault.io"
    assert company.contacts[0].verification_status == "valid"


def test_pipeline_run_checkpoint_granularity(db_session):
    """
    Verifies that PipelineRun tracks last_completed_stage so interrupted runs
    can resume from email_resolved directly to drafting without re-running discovery or Hunter.
    """
    user = User(email="run_user@raghavpathak.me", password_hash="hash")
    campaign = Campaign(user=user, name="Run Campaign", objective="Objective")
    company = Company(campaign=campaign, domain="resume-test.io", company_name="Resume Test")
    db_session.add_all([user, campaign, company])
    db_session.commit()

    # 1. Started run
    run = PipelineRun(
        campaign_id=campaign.id,
        company_id=company.id,
        status="running",
        started_at=datetime.now(timezone.utc)
    )
    db_session.add(run)
    db_session.commit()

    # 2. Stage 1 completes: person verified
    run.last_completed_stage = "person_verified"
    db_session.commit()

    # 3. Stage 2 completes: email resolved
    run.last_completed_stage = "email_resolved"
    db_session.commit()

    # Query interrupted runs that reached email resolution
    interrupted = db_session.execute(
        select(PipelineRun).where(
            PipelineRun.status == "running",
            PipelineRun.last_completed_stage == "email_resolved"
        )
    ).scalar_one()

    assert interrupted.id == run.id
    assert interrupted.last_completed_stage == "email_resolved"

    # Simulate resume to drafting and waiting_for_review
    interrupted.last_completed_stage = "draft_generated"
    interrupted.status = "waiting_for_review"
    db_session.commit()

    db_session.refresh(run)
    assert run.status == "waiting_for_review"
    assert run.last_completed_stage == "draft_generated"


def test_draft_review_and_delivery_lifecycle(db_session):
    """Verifies Draft generation, Review approval, and Delivery staging records."""
    user = User(email="delivery_user@raghavpathak.me", password_hash="hash")
    campaign = Campaign(user=user, name="Delivery Campaign", objective="Objective")
    company = Company(campaign=campaign, domain="secure-mesh.io", company_name="Secure Mesh")
    run = PipelineRun(campaign=campaign, company=company, status="waiting_for_review")
    db_session.add_all([user, campaign, company, run])
    db_session.commit()

    # Draft generated
    draft = Draft(
        pipeline_run_id=run.id,
        company_id=company.id,
        subject="Technical Collaboration in Confidential Computing",
        body="Hi Arjun,\n\nI noticed Secure Mesh is scaling confidential computing...",
        persona="security"
    )
    db_session.add(draft)
    db_session.commit()

    # Review created in pending state
    review = Review(
        pipeline_run_id=run.id,
        draft_id=draft.id,
        status="pending"
    )
    db_session.add(review)
    db_session.commit()

    assert review.status == "pending"

    # Human operator edits and approves
    review.status = "approved"
    review.edited_subject = "Encrypted State Channels at Secure Mesh"
    review.edited_body = "Hi Arjun,\n\nRefined pitch text..."
    review.reviewed_at = datetime.now(timezone.utc)
    db_session.commit()

    # Authoritative Delivery staged
    delivery = Delivery(
        pipeline_run_id=run.id,
        company_id=company.id,
        delivery_mode="staged",
        delivery_status="staged",
        provider="instantly",
        staged_file_path="staged_deliveries/live_staged_secure-mesh_io_20260915_180000.json",
        safety_audit_json='{"dry_run": true, "email_verified": true, "person_conf": 0.95}'
    )
    db_session.add(delivery)
    run.status = "completed"
    run.completed_at = datetime.now(timezone.utc)
    db_session.commit()

    db_session.refresh(run)
    assert run.status == "completed"
    assert run.delivery is not None
    assert run.delivery.delivery_status == "staged"
    assert run.delivery.provider == "instantly"


def test_revoked_token_management(db_session):
    """Verifies RevokedToken storage and querying for session logout invalidation."""
    now = datetime.now(timezone.utc)
    token = RevokedToken(
        jti="jwt_token_unique_id_999",
        expires_at=now + timedelta(hours=2)
    )
    db_session.add(token)
    db_session.commit()

    found = db_session.execute(
        select(RevokedToken).where(RevokedToken.jti == "jwt_token_unique_id_999")
    ).scalar_one_or_none()

    assert found is not None
    assert found.jti == "jwt_token_unique_id_999"

    not_found = db_session.execute(
        select(RevokedToken).where(RevokedToken.jti == "non_existent_token")
    ).scalar_one_or_none()
    assert not_found is None


def test_pipeline_event_lifecycle(db_session):
    """Verifies PipelineEvent tracking for granular audit logging of pipeline runs."""
    user = User(email="events_user@raghavpathak.me", password_hash="hash")
    campaign = Campaign(user=user, name="Event Tracking Campaign", objective="Track events")
    company = Company(campaign=campaign, domain="event-stream.io", company_name="Event Stream")
    run = PipelineRun(campaign=campaign, company=company, status="running")
    db_session.add_all([user, campaign, company, run])
    db_session.commit()

    event1 = PipelineEvent(
        campaign_id=campaign.id,
        pipeline_run_id=run.id,
        event_type="discovery",
        message="Discovered company event-stream.io via Apollo",
        data_json='{"source": "apollo", "confidence": 0.9}'
    )
    event2 = PipelineEvent(
        campaign_id=campaign.id,
        pipeline_run_id=run.id,
        event_type="email_resolved",
        message="Resolved deliverable email for CTO",
        data_json='{"email": "cto@event-stream.io", "provider": "hunter"}'
    )
    db_session.add_all([event1, event2])
    db_session.commit()

    events = db_session.execute(
        select(PipelineEvent)
        .where(PipelineEvent.pipeline_run_id == run.id)
        .order_by(PipelineEvent.created_at.asc())
    ).scalars().all()

    assert len(events) == 2
    assert events[0].event_type == "discovery"
    assert events[1].event_type == "email_resolved"
    assert events[1].pipeline_run.id == run.id
    assert events[1].campaign.id == campaign.id


def test_full_cascade_deletion(db_session):
    """
    Verifies that deleting a Campaign cascades and cleans up all child entities:
    Companies, Persons, Contacts, PipelineRuns, Drafts, Reviews, Deliveries, and Events.
    """
    user = User(email="cascade_user@raghavpathak.me", password_hash="hash")
    resume = Resume(user=user, filename="test.pdf", file_path="path/to/test.pdf")
    campaign = Campaign(user=user, resume=resume, name="Cascade Test", objective="Cascade")
    company = Company(campaign=campaign, domain="cascade-target.io", company_name="Cascade Target")
    person = Person(
        company=company,
        first_name="Jane",
        last_name="Doe",
        full_name="Jane Doe",
        role="CISO"
    )
    contact = Contact(
        company=company,
        person=person,
        email="jane@cascade-target.io",
        verification_status="valid"
    )
    run = PipelineRun(campaign=campaign, company=company, status="waiting_for_review")
    draft = Draft(
        pipeline_run=run,
        company=company,
        contact=contact,
        subject="Subject",
        body="Body"
    )
    review = Review(pipeline_run=run, draft=draft, status="pending")
    delivery = Delivery(
        pipeline_run=run,
        company=company,
        contact=contact,
        delivery_mode="staged",
        delivery_status="staged"
    )
    event = PipelineEvent(
        campaign=campaign,
        pipeline_run=run,
        event_type="test",
        message="Test event"
    )

    db_session.add_all([user, resume, campaign, company, person, contact, run, draft, review, delivery, event])
    db_session.commit()

    company_id = company.id
    run_id = run.id
    draft_id = draft.id
    review_id = review.id
    delivery_id = delivery.id
    event_id = event.id
    person_id = person.id
    contact_id = contact.id

    # Delete campaign: should cascade to company, person, contact, run, draft, review, delivery, event
    db_session.delete(campaign)
    db_session.commit()

    assert db_session.execute(select(Company).where(Company.id == company_id)).scalar_one_or_none() is None
    assert db_session.execute(select(Person).where(Person.id == person_id)).scalar_one_or_none() is None
    assert db_session.execute(select(Contact).where(Contact.id == contact_id)).scalar_one_or_none() is None
    assert db_session.execute(select(PipelineRun).where(PipelineRun.id == run_id)).scalar_one_or_none() is None
    assert db_session.execute(select(Draft).where(Draft.id == draft_id)).scalar_one_or_none() is None
    assert db_session.execute(select(Review).where(Review.id == review_id)).scalar_one_or_none() is None
    assert db_session.execute(select(Delivery).where(Delivery.id == delivery_id)).scalar_one_or_none() is None
    assert db_session.execute(select(PipelineEvent).where(PipelineEvent.id == event_id)).scalar_one_or_none() is None


def test_init_db_and_reset_db(tmp_path):
    """Verifies that init_db creates all tables and reset_db drops and recreates them cleanly."""
    from server.database import init_db, reset_db
    from sqlalchemy import inspect

    test_db_file = tmp_path / "test_init_reset.db"
    test_db_url = f"sqlite:///{test_db_file}"
    engine = create_db_engine(db_url=test_db_url)

    try:
        init_db(target_engine=engine)
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        expected_tables = {
            "users", "profiles", "resumes", "campaigns", "companies",
            "persons", "contacts", "pipeline_runs", "drafts", "reviews",
            "deliveries", "pipeline_events", "revoked_tokens"
        }
        for table in expected_tables:
            assert table in tables, f"Expected table {table} not found in database"

        # reset_db drops and recreates
        reset_db(target_engine=engine)
        inspector = inspect(engine)
        tables_after_reset = inspector.get_table_names()
        for table in expected_tables:
            assert table in tables_after_reset
    finally:
        engine.dispose()

