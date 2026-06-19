"""initial_schema

Revision ID: 08d50a4779ea
Revises: 
Create Date: 2026-05-27 12:39:10.650835
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '08d50a4779ea'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.create_table('users',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('email', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('email'),
    )

    op.create_table('jobs',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=True),
        sa.Column('status', sa.String(), nullable=True),
        sa.Column('progress', sa.Integer(), nullable=True),
        sa.Column('message', sa.String(), nullable=True),
        sa.Column('stage', sa.String(), nullable=True),
        sa.Column('stage_started_at', sa.DateTime(), nullable=True),
        sa.Column('stage_completed_at', sa.DateTime(), nullable=True),
        sa.Column('retry_count', sa.Integer(), nullable=True),
        sa.Column('max_retries', sa.Integer(), nullable=True),
        sa.Column('temp_paths', sa.JSON(), nullable=True),
        sa.Column('checkpoint_data', sa.JSON(), nullable=True),
        sa.Column('video_path', sa.String(), nullable=True),
        sa.Column('source', sa.String(), nullable=True),
        sa.Column('provider', sa.String(), nullable=True),
        sa.Column('preset', sa.String(), nullable=True),
        sa.Column('caption_style', sa.String(), nullable=True),
        sa.Column('download_quality', sa.String(), nullable=True),
        sa.Column('video_duration', sa.Float(), nullable=True),
        sa.Column('video_resolution', sa.String(), nullable=True),
        sa.Column('source_hash', sa.String(), nullable=True),
        sa.Column('transcript', sa.JSON(), nullable=True),
        sa.Column('clip_candidates', sa.JSON(), nullable=True),
        sa.Column('clips', sa.JSON(), nullable=True),
        sa.Column('errors', sa.JSON(), nullable=True),
        sa.Column('stage_timings', sa.JSON(), nullable=True),
        sa.Column('archived_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
    )
    op.create_index('ix_jobs_id', 'jobs', ['id'])

    op.create_table('clips',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('job_id', sa.String(), nullable=False),
        sa.Column('filename', sa.String(), nullable=False),
        sa.Column('title', sa.String(), nullable=True),
        sa.Column('hook_caption', sa.String(), nullable=True),
        sa.Column('virality_score', sa.Float(), nullable=True),
        sa.Column('reason', sa.String(), nullable=True),
        sa.Column('category', sa.String(), nullable=True),
        sa.Column('hashtags', sa.JSON(), nullable=True),
        sa.Column('start_time', sa.Float(), nullable=False),
        sa.Column('end_time', sa.Float(), nullable=False),
        sa.Column('duration', sa.Float(), nullable=False),
        sa.Column('storage_path', sa.String(), nullable=True),
        sa.Column('thumbnail_path', sa.String(), nullable=True),
        sa.Column('subtitle_path', sa.String(), nullable=True),
        sa.Column('content_hash', sa.String(), nullable=True),
        sa.Column('render_version', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(), nullable=True),
        sa.Column('words', sa.JSON(), nullable=True),
        sa.Column('context_start', sa.Float(), nullable=True),
        sa.Column('hook_start', sa.Float(), nullable=True),
        sa.Column('payoff_end', sa.Float(), nullable=True),
        sa.Column('judge_provider', sa.String(), nullable=True),
        sa.Column('judge_model', sa.String(), nullable=True),
        sa.Column('judge_notes', sa.JSON(), nullable=True),
        sa.Column('signal_scores', sa.JSON(), nullable=True),
        sa.Column('psychology_scores', sa.JSON(), nullable=True),
        sa.Column('quality_filter_results', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['job_id'], ['jobs.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_clips_job_id', 'clips', ['job_id'])

    op.create_table('clip_analytics',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('clip_id', sa.String(), nullable=False),
        sa.Column('preview_views', sa.Integer(), nullable=True),
        sa.Column('preview_total_watch_ms', sa.Integer(), nullable=True),
        sa.Column('downloads', sa.Integer(), nullable=True),
        sa.Column('exports', sa.Integer(), nullable=True),
        sa.Column('favorites', sa.Integer(), nullable=True),
        sa.Column('shares', sa.Integer(), nullable=True),
        sa.Column('rejects', sa.Integer(), nullable=True),
        sa.Column('regenerations', sa.Integer(), nullable=True),
        sa.Column('boundary_edits', sa.Integer(), nullable=True),
        sa.Column('user_rating', sa.Float(), nullable=True),
        sa.Column('watch_completion_rate', sa.Float(), nullable=True),
        sa.Column('avg_watch_duration_ms', sa.Integer(), nullable=True),
        sa.Column('last_interaction', sa.DateTime(), nullable=True),
        sa.Column('interaction_history', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['clip_id'], ['clips.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('clip_id'),
    )
    op.create_index('ix_clip_analytics_clip_id', 'clip_analytics', ['clip_id'])


def downgrade():
    op.drop_table('clip_analytics')
    op.drop_table('clips')
    op.drop_table('jobs')
    op.drop_table('users')
