"""BWF domain models — clean Pydantic schema for Smallink embedding."""

from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class GenerationStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class ImageVariant(BaseModel):
    id: str
    url: str
    created_at: float = Field(default_factory=time.time)
    prompt_used: Optional[str] = None
    model: Optional[str] = None
    seed: Optional[int] = None
    is_favorited: bool = False


class VideoVariant(BaseModel):
    id: str
    url: str
    created_at: float = Field(default_factory=time.time)
    prompt_used: Optional[str] = None
    source_image_id: Optional[str] = None
    is_favorited: bool = False


class AssetUnit(BaseModel):
    selected_image_id: Optional[str] = None
    image_variants: List[ImageVariant] = Field(default_factory=list)
    selected_video_id: Optional[str] = None
    video_variants: List[VideoVariant] = Field(default_factory=list)
    image_prompt: Optional[str] = None
    video_prompt: Optional[str] = None


class CameraMovement(BaseModel):
    primary: str
    secondary: Optional[str] = None
    speed: str = "normal"
    description: Optional[str] = None


class DialogueLine(BaseModel):
    speaker: str
    line: str
    emotion: Optional[str] = None


class AudioNote(BaseModel):
    sfx: Optional[str] = None
    ambience: Optional[str] = None
    bgm_note: Optional[str] = None


# ── Entities ──

class Character(BaseModel):
    id: str
    name: str
    description: str = ""
    persona: str = ""
    age: Optional[str] = None
    gender: Optional[str] = None
    clothing: Optional[str] = None
    visual_weight: int = 3
    reference_sheet: AssetUnit = Field(default_factory=AssetUnit)
    voice_id: Optional[str] = None
    voice_name: Optional[str] = None
    voice_speed: float = 1.0
    voice_origin: str = "system"
    locked: bool = False
    starred: bool = False
    status: GenerationStatus = GenerationStatus.PENDING


class Scene(BaseModel):
    id: str
    name: str
    description: str = ""
    visual_weight: int = 3
    time_of_day: Optional[str] = None
    lighting_mood: Optional[str] = None
    reference_sheet: AssetUnit = Field(default_factory=AssetUnit)
    locked: bool = False
    starred: bool = False
    status: GenerationStatus = GenerationStatus.PENDING


class Prop(BaseModel):
    id: str
    name: str
    description: str = ""
    reference_sheet: AssetUnit = Field(default_factory=AssetUnit)
    locked: bool = False
    starred: bool = False
    status: GenerationStatus = GenerationStatus.PENDING


# ── Video Task ──

class VideoTask(BaseModel):
    id: str
    project_id: str
    frame_id: Optional[str] = None
    asset_id: Optional[str] = None
    image_url: str = ""
    prompt: str = ""
    status: str = "pending"
    error: Optional[str] = None
    video_url: Optional[str] = None
    duration: int = 5
    model: str = "wan2.7-i2v"
    generation_mode: str = "i2v"
    provider_name: Optional[str] = None
    provider_task_id: Optional[str] = None
    is_starred: bool = False
    label: Optional[str] = None
    workbench_tab: Optional[str] = None
    source_type: str = "native"
    provider_params: Dict[str, Any] = Field(default_factory=dict)
    created_at: float = Field(default_factory=time.time)


# ── Storyboard Frame ──

class StoryboardFrame(BaseModel):
    id: str
    scene_id: str = ""
    character_ids: List[str] = Field(default_factory=list)
    prop_ids: List[str] = Field(default_factory=list)
    visual_description: Optional[str] = None
    visual_atmosphere: Optional[str] = None
    character_acting: Optional[str] = None
    key_action_physics: Optional[str] = None
    shot_size: Optional[str] = None
    camera_movement: Optional[CameraMovement] = None
    composition: Optional[str] = None
    dialogue: Optional[DialogueLine] = None
    audio_note: Optional[AudioNote] = None
    duration: Optional[int] = None
    transition_hint: Optional[str] = None
    prompt_cn: Optional[str] = None
    prompt_en: Optional[str] = None
    assembled_prompt: Optional[str] = None
    image: AssetUnit = Field(default_factory=AssetUnit)
    selected_video_id: Optional[str] = None
    is_video_pinned: bool = False
    audio_url: Optional[str] = None
    dubbed_video_url: Optional[str] = None
    bwf_narrative_goal: str = ""
    bwf_transition_intent: str = ""
    bwf_review_status: str = "draft"
    workbench_tab_mode: Optional[str] = None
    final_take_id: Optional[str] = None
    locked: bool = False
    status: GenerationStatus = GenerationStatus.PENDING
    updated_at: float = Field(default_factory=time.time)


# ── Configuration ──

class ModelSettings(BaseModel):
    image_model: str = "wan2.7-image-pro"
    i2v_model: str = "happyhorse-1.1-i2v"
    r2v_model: str = "happyhorse-1.1-r2v"
    character_aspect_ratio: str = "9:16"
    scene_aspect_ratio: str = "16:9"
    storyboard_aspect_ratio: str = "16:9"


class PromptConfig(BaseModel):
    storyboard_polish: str = ""
    video_polish: str = ""
    r2v_polish: str = ""
    entity_extraction: str = ""
    storyboard_extraction: str = ""
    polish_model: str = ""


class ArtDirection(BaseModel):
    selected_style_id: str
    style_config: Dict[str, Any] = Field(default_factory=dict)
    custom_styles: List[Dict[str, Any]] = Field(default_factory=list)


class BWFBrief(BaseModel):
    content_type: str = "narrative"
    platform: str = "custom"
    target_duration_seconds: int = 60
    aspect_ratio: str = "9:16"
    fps: int = 24
    audience: str = ""
    objective: str = ""
    visual_tone: str = ""


class BWFBeat(BaseModel):
    id: str = Field(default_factory=lambda: f"beat_{uuid.uuid4().hex[:12]}")
    order: int = 0
    title: str = ""
    narrative_goal: str = ""
    narration: str = ""
    target_duration_seconds: int = 6
    mood: str = ""


class CustomVoice(BaseModel):
    id: str
    label: str
    origin: str
    target_model: str = "cosyvoice-v3.5-plus"
    created_at: float = Field(default_factory=time.time)
    source_audio_url: Optional[str] = None
    voice_prompt: Optional[str] = None


# ── Top-Level Aggregates ──

class Project(BaseModel):
    id: str
    title: str
    original_text: str = ""
    characters: List[Character] = Field(default_factory=list)
    scenes: List[Scene] = Field(default_factory=list)
    props: List[Prop] = Field(default_factory=list)
    frames: List[StoryboardFrame] = Field(default_factory=list)
    video_tasks: List[VideoTask] = Field(default_factory=list)
    art_direction: Optional[ArtDirection] = None
    model_settings: ModelSettings = Field(default_factory=ModelSettings)
    prompt_config: PromptConfig = Field(default_factory=PromptConfig)
    workflow_mode: str = "r2v"
    default_generation_mode: str = "r2v"
    bwf_brief: Optional[BWFBrief] = None
    bwf_beats: List[BWFBeat] = Field(default_factory=list)
    merged_video_url: Optional[str] = None
    merged_video_signature: Optional[str] = None
    bgm_url: Optional[str] = None
    mix_settings: Dict[str, int] = Field(default_factory=lambda: {"dialogue": 100, "bgm": 35})
    series_id: Optional[str] = None
    episode_number: Optional[int] = None
    starred: bool = False
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)


class Series(BaseModel):
    id: str
    title: str
    description: str = ""
    characters: List[Character] = Field(default_factory=list)
    scenes: List[Scene] = Field(default_factory=list)
    props: List[Prop] = Field(default_factory=list)
    art_direction: Optional[ArtDirection] = None
    model_settings: ModelSettings = Field(default_factory=ModelSettings)
    prompt_config: PromptConfig = Field(default_factory=PromptConfig)
    workflow_mode: str = "r2v"
    default_generation_mode: str = "r2v"
    content_mode: str = "scripted"
    custom_voices: List[CustomVoice] = Field(default_factory=list)
    episode_ids: List[str] = Field(default_factory=list)
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)
