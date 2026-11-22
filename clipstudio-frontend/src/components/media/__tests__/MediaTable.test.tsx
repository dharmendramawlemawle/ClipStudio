import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, act } from '@testing-library/react';
import { MediaTable } from '../MediaTable';
import { ImportedVideo } from '../../../types';

vi.mock('../../../api/client', async () => {
  const actual = await vi.importActual<any>('../../../api/client');
  return {
    ...actual,
    fetchThumbnailMetadata: vi.fn().mockResolvedValue({
      media_id: 'vid-completed',
      status: 'completed',
      width: 640,
      height: 360,
      file_size_bytes: 42500,
    }),
  };
});

const baseVideo: ImportedVideo = {
  id: 'vid-123',
  workspace_id: 'ws-default',
  file_name: 'hero_presentation.mp4',
  file_path: 'media/hero_presentation.mp4',
  file_size_bytes: 10485760,
  duration_seconds: 125,
  width: 1920,
  height: 1080,
  fps: 30,
  video_codec: 'h264',
  audio_codec: 'aac',
  container_format: 'mp4',
  status: 'ready',
  sha256: 'a1b2c3d4e5f6',
  created_at: '2026-11-22T10:00:00Z',
  updated_at: '2026-11-22T10:00:00Z',
};

describe('MediaTable Component - Thumbnail Engine Integration (Phase 2B.2)', () => {
  it('renders loading state when isLoading is true', () => {
    render(
      <MediaTable
        videos={[]}
        isLoading={true}
        onDeleteVideo={vi.fn()}
      />
    );
    expect(screen.getByText(/Loading imported video assets/i)).toBeDefined();
  });

  it('renders empty workspace state when videos array is empty', () => {
    render(
      <MediaTable
        videos={[]}
        isLoading={false}
        onDeleteVideo={vi.fn()}
      />
    );
    expect(screen.getByText(/No Videos in this Workspace/i)).toBeDefined();
  });

  it('renders completed thumbnail with image, duration badge, and preview trigger', async () => {
    const videoCompleted: ImportedVideo = {
      ...baseVideo,
      id: 'vid-completed',
      file_name: 'completed_video.mp4',
      thumbnail_status: 'completed',
      thumbnail_path: 'data/media/thumbnails/ws-default/vid-completed/thumbnail.jpg',
      duration_seconds: 75,
    };

    render(
      <MediaTable
        videos={[videoCompleted]}
        isLoading={false}
        onDeleteVideo={vi.fn()}
      />
    );

    // Image rendered with correct src and alt
    const img = screen.getByAltText('completed_video.mp4') as HTMLImageElement;
    expect(img).toBeDefined();
    expect(img.src).toContain('/api/v1/media/vid-completed/thumbnail');

    // Duration badge formatted (75s -> 1:15, appears in badge and duration column)
    const durationElements = screen.getAllByText('1:15');
    expect(durationElements.length).toBeGreaterThanOrEqual(2);

    // Clicking thumbnail opens preview modal
    const thumbnailWrapper = screen.getByTitle('Click to preview thumbnail');
    await act(async () => {
      fireEvent.click(thumbnailWrapper);
    });

    // Modal should now be visible with Close button, video details, and actual thumbnail dimensions
    const closeBtn = screen.getByRole('button', { name: 'Close' });
    expect(closeBtn).toBeDefined();
    expect(screen.getAllByText(/1920x1080/).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/640x360px/)).toBeDefined();

    // Clicking Close closes modal
    await act(async () => {
      fireEvent.click(closeBtn);
    });
    expect(screen.queryByRole('button', { name: 'Close' })).toBeNull();
  });

  it('renders processing state with spinner and extracting label', () => {
    const videoProcessing: ImportedVideo = {
      ...baseVideo,
      id: 'vid-proc',
      thumbnail_status: 'processing',
    };

    render(
      <MediaTable
        videos={[videoProcessing]}
        isLoading={false}
        onDeleteVideo={vi.fn()}
      />
    );

    expect(screen.getByText('Extracting...')).toBeDefined();
  });

  it('renders accurate pending state when thumbnail_status is pending with manual start button', async () => {
    const onRegenerateMock = vi.fn().mockResolvedValue(undefined);
    const videoPending: ImportedVideo = {
      ...baseVideo,
      id: 'vid-pending',
      thumbnail_status: 'pending',
    };

    render(
      <MediaTable
        videos={[videoPending]}
        isLoading={false}
        onDeleteVideo={vi.fn()}
        onRegenerateThumbnail={onRegenerateMock}
      />
    );

    const pendingBtn = screen.getByRole('button', { name: /Pending \(Start\)/i });
    expect(pendingBtn).toBeDefined();

    await act(async () => {
      fireEvent.click(pendingBtn);
    });
    expect(onRegenerateMock).toHaveBeenCalledWith('vid-pending');
  });

  it('renders queued state when thumbnail_status is queued (active background job exists)', () => {
    const videoQueued: ImportedVideo = {
      ...baseVideo,
      id: 'vid-queued',
      thumbnail_status: 'queued',
    };

    render(
      <MediaTable
        videos={[videoQueued]}
        isLoading={false}
        onDeleteVideo={vi.fn()}
      />
    );

    expect(screen.getByText('Queued')).toBeDefined();
  });

  it('renders failed state with retry button and calls onRegenerateThumbnail on click', async () => {
    const onRegenerateMock = vi.fn().mockResolvedValue(undefined);
    const videoFailed: ImportedVideo = {
      ...baseVideo,
      id: 'vid-failed',
      thumbnail_status: 'failed',
    };

    render(
      <MediaTable
        videos={[videoFailed]}
        isLoading={false}
        onDeleteVideo={vi.fn()}
        onRegenerateThumbnail={onRegenerateMock}
      />
    );

    const retryBtn = screen.getByRole('button', { name: /retry/i });
    expect(retryBtn).toBeDefined();
    expect(screen.getByText('Thumb failed')).toBeDefined();

    await act(async () => {
      fireEvent.click(retryBtn);
    });
    expect(onRegenerateMock).toHaveBeenCalledWith('vid-failed');
  });

  it('renders missing thumbnail fallback with generate button', async () => {
    const onRegenerateMock = vi.fn().mockResolvedValue(undefined);
    const videoMissing: ImportedVideo = {
      ...baseVideo,
      id: 'vid-missing',
      thumbnail_status: undefined,
      thumbnail_path: null,
    };

    render(
      <MediaTable
        videos={[videoMissing]}
        isLoading={false}
        onDeleteVideo={vi.fn()}
        onRegenerateThumbnail={onRegenerateMock}
      />
    );

    const generateBtn = screen.getByRole('button', { name: /generate/i });
    expect(generateBtn).toBeDefined();

    await act(async () => {
      fireEvent.click(generateBtn);
    });
    expect(onRegenerateMock).toHaveBeenCalledWith('vid-missing');
  });

  it('provides regenerate action button in table action column', async () => {
    const onRegenerateMock = vi.fn().mockResolvedValue(undefined);
    const video: ImportedVideo = {
      ...baseVideo,
      id: 'vid-action',
      thumbnail_status: 'completed',
      thumbnail_path: 'data/media/thumbnails/ws-default/vid-action/thumbnail.jpg',
    };

    render(
      <MediaTable
        videos={[video]}
        isLoading={false}
        onDeleteVideo={vi.fn()}
        onRegenerateThumbnail={onRegenerateMock}
      />
    );

    const regenerateActionBtn = screen.getByTitle('Regenerate Video Thumbnail');
    expect(regenerateActionBtn).toBeDefined();

    await act(async () => {
      fireEvent.click(regenerateActionBtn);
    });
    expect(onRegenerateMock).toHaveBeenCalledWith('vid-action');
  });
});
