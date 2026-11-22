import React, { useState, useEffect } from 'react';
import {
  FileVideo,
  Trash2,
  Clock,
  Film,
  HardDrive,
  Calendar,
  CheckCircle2,
  AlertCircle,
  Loader2,
  RefreshCw,
  Eye,
  X,
  Image as ImageIcon,
} from 'lucide-react';
import { ImportedVideo, ThumbnailMetadata } from '../../types';
import { getThumbnailUrl, regenerateThumbnail, fetchThumbnailMetadata } from '../../api/client';

interface MediaTableProps {
  videos: ImportedVideo[];
  isLoading: boolean;
  onDeleteVideo: (videoId: string) => Promise<void>;
  onRegenerateThumbnail?: (videoId: string) => Promise<void>;
}

export const MediaTable: React.FC<MediaTableProps> = ({
  videos,
  isLoading,
  onDeleteVideo,
  onRegenerateThumbnail,
}) => {
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [regeneratingId, setRegeneratingId] = useState<string | null>(null);
  const [actionMessage, setActionMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const [previewVideo, setPreviewVideo] = useState<ImportedVideo | null>(null);
  const [previewMetadata, setPreviewMetadata] = useState<ThumbnailMetadata | null>(null);

  useEffect(() => {
    if (previewVideo && previewVideo.thumbnail_status === 'completed') {
      fetchThumbnailMetadata(previewVideo.id)
        .then((meta) => setPreviewMetadata(meta))
        .catch(() => setPreviewMetadata(null));
    } else {
      setPreviewMetadata(null);
    }
  }, [previewVideo]);

  const formatDuration = (seconds: number) => {
    if (!seconds || seconds <= 0) return '0:00';
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = Math.floor(seconds % 60);

    if (h > 0) {
      return `${h}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
    }
    return `${m}:${s.toString().padStart(2, '0')}`;
  };

  const formatBytes = (bytes: number) => {
    if (!bytes || bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return `${(bytes / Math.pow(k, i)).toFixed(1)} ${sizes[i]}`;
  };

  const formatDate = (isoStr: string) => {
    try {
      const d = new Date(isoStr);
      return d.toLocaleDateString(undefined, {
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      });
    } catch {
      return isoStr;
    }
  };

  const handleDelete = async (videoId: string) => {
    if (!window.confirm('Are you sure you want to delete this media asset and source file?')) {
      return;
    }
    setDeletingId(videoId);
    setDeleteError(null);
    try {
      await onDeleteVideo(videoId);
      setActionMessage({ type: 'success', text: 'Media asset deleted successfully.' });
    } catch (err: any) {
      setDeleteError(err.message || 'Failed to delete media asset.');
    } finally {
      setDeletingId(null);
    }
  };

  const handleRegenerate = async (videoId: string) => {
    setRegeneratingId(videoId);
    setActionMessage(null);
    try {
      if (onRegenerateThumbnail) {
        await onRegenerateThumbnail(videoId);
      } else {
        await regenerateThumbnail(videoId);
      }
      setActionMessage({ type: 'success', text: 'Thumbnail generation queued successfully.' });
    } catch (err: any) {
      setActionMessage({ type: 'error', text: err.message || 'Failed to enqueue thumbnail generation.' });
    } finally {
      setRegeneratingId(null);
    }
  };

  if (isLoading) {
    return (
      <div className="bg-studio-900 border border-studio-800 rounded-2xl p-12 flex flex-col items-center justify-center space-y-3">
        <Loader2 className="w-8 h-8 animate-spin text-brand-500" />
        <p className="text-sm text-studio-400">Loading imported video assets...</p>
      </div>
    );
  }

  if (videos.length === 0) {
    return (
      <div className="bg-studio-900 border border-studio-800 rounded-2xl p-16 flex flex-col items-center justify-center text-center space-y-4">
        <div className="p-4 rounded-2xl bg-studio-800/60 text-studio-400 border border-studio-700/50">
          <FileVideo className="w-10 h-10" />
        </div>
        <div className="max-w-sm">
          <h3 className="text-base font-semibold text-white">No Videos in this Workspace</h3>
          <p className="text-xs text-studio-400 mt-1">
            Import long-form MP4, MKV, or MOV files to begin video clipping and stream ingestion.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {deleteError && (
        <div className="bg-red-500/10 border border-red-500/20 text-red-400 px-4 py-3 rounded-xl text-xs flex items-center space-x-2">
          <AlertCircle className="w-4 h-4 shrink-0" />
          <span>{deleteError}</span>
        </div>
      )}

      {actionMessage && (
        <div
          className={`px-4 py-2.5 rounded-xl text-xs flex items-center justify-between border ${
            actionMessage.type === 'success'
              ? 'bg-emerald-500/10 border-emerald-500/20 text-emerald-400'
              : 'bg-red-500/10 border-red-500/20 text-red-400'
          }`}
        >
          <div className="flex items-center space-x-2">
            {actionMessage.type === 'success' ? (
              <CheckCircle2 className="w-4 h-4 shrink-0" />
            ) : (
              <AlertCircle className="w-4 h-4 shrink-0" />
            )}
            <span>{actionMessage.text}</span>
          </div>
          <button
            onClick={() => setActionMessage(null)}
            className="text-studio-400 hover:text-white"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      )}

      <div className="bg-studio-900 border border-studio-800 rounded-2xl overflow-hidden shadow-xl">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="bg-studio-950/80 border-b border-studio-800 text-studio-400 font-medium uppercase tracking-wider text-[11px]">
              <tr>
                <th className="py-3.5 px-4">Thumbnail</th>
                <th className="py-3.5 px-4">Media File</th>
                <th className="py-3.5 px-4">Resolution & FPS</th>
                <th className="py-3.5 px-4">Duration</th>
                <th className="py-3.5 px-4">Codecs</th>
                <th className="py-3.5 px-4">Size</th>
                <th className="py-3.5 px-4">Status</th>
                <th className="py-3.5 px-4">Imported</th>
                <th className="py-3.5 px-4 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-studio-800/60 text-studio-200">
              {videos.map((v) => {
                const thumbStatus = v.thumbnail_status || (v.thumbnail_path ? 'completed' : 'pending');

                return (
                  <tr key={v.id} className="hover:bg-studio-850/50 transition">
                    {/* Thumbnail Column */}
                    <td className="py-3 px-4 whitespace-nowrap">
                      {thumbStatus === 'completed' && v.thumbnail_path ? (
                        <div
                          className="relative group w-28 h-16 rounded-xl overflow-hidden bg-studio-950 border border-studio-800 shrink-0 cursor-pointer shadow-sm hover:border-brand-500/50 transition"
                          onClick={() => setPreviewVideo(v)}
                          title="Click to preview thumbnail"
                        >
                          <img
                            src={getThumbnailUrl(v.id)}
                            alt={v.file_name}
                            className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-200"
                            loading="lazy"
                            onError={(e) => {
                              // If image fails to load, fallback visually
                              (e.target as HTMLElement).style.display = 'none';
                            }}
                          />
                          <div className="absolute inset-0 bg-black/20 group-hover:bg-transparent transition-colors flex items-center justify-center opacity-0 group-hover:opacity-100">
                            <span className="p-1 rounded-full bg-black/60 text-white backdrop-blur-xs">
                              <Eye className="w-3.5 h-3.5" />
                            </span>
                          </div>
                          <span className="absolute bottom-1 right-1 px-1.5 py-0.5 rounded text-[9px] font-mono bg-black/75 text-white backdrop-blur-xs">
                            {formatDuration(v.duration_seconds)}
                          </span>
                        </div>
                      ) : thumbStatus === 'processing' || thumbStatus === 'running' ? (
                        <div className="w-28 h-16 rounded-xl bg-studio-950/80 border border-brand-500/30 flex flex-col items-center justify-center space-y-1 shrink-0 p-1 text-center">
                          <Loader2 className="w-4 h-4 animate-spin text-brand-500" />
                          <span className="text-[9px] text-brand-400 font-medium">Extracting...</span>
                        </div>
                      ) : thumbStatus === 'failed' ? (
                        <div className="w-28 h-16 rounded-xl bg-red-950/20 border border-red-500/30 flex flex-col items-center justify-center space-y-1 shrink-0 p-1 text-center">
                          <AlertCircle className="w-3.5 h-3.5 text-red-400" />
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              handleRegenerate(v.id);
                            }}
                            disabled={regeneratingId === v.id}
                            className="text-[10px] text-red-400 hover:text-red-300 font-semibold underline disabled:opacity-50"
                          >
                            {regeneratingId === v.id ? 'Retrying...' : 'Retry'}
                          </button>
                        </div>
                      ) : thumbStatus === 'queued' ? (
                        <div className="w-28 h-16 rounded-xl bg-studio-950/80 border border-studio-800 flex flex-col items-center justify-center space-y-1 shrink-0 p-1 text-center">
                          <Clock className="w-3.5 h-3.5 text-amber-500/80" />
                          <span className="text-[9px] text-studio-400 font-medium">Queued</span>
                        </div>
                      ) : thumbStatus === 'pending' || thumbStatus === 'pending_recovery' ? (
                        <div className="w-28 h-16 rounded-xl bg-amber-950/20 border border-amber-500/30 flex flex-col items-center justify-center space-y-1 shrink-0 p-1 text-center">
                          <Clock className="w-3.5 h-3.5 text-amber-400" />
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              handleRegenerate(v.id);
                            }}
                            disabled={regeneratingId === v.id}
                            className="text-[9px] text-amber-400 hover:text-amber-300 font-medium underline disabled:opacity-50"
                          >
                            {regeneratingId === v.id ? 'Starting...' : 'Pending (Start)'}
                          </button>
                        </div>
                      ) : (
                        <div className="w-28 h-16 rounded-xl bg-studio-950/80 border border-studio-800 flex flex-col items-center justify-center space-y-1 shrink-0 p-1 text-center">
                          <FileVideo className="w-4 h-4 text-studio-500" />
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              handleRegenerate(v.id);
                            }}
                            disabled={regeneratingId === v.id}
                            className="text-[9px] text-brand-400 hover:text-brand-300 font-medium underline"
                          >
                            Generate
                          </button>
                        </div>
                      )}
                    </td>

                    {/* File Name */}
                    <td className="py-3 px-4 font-medium text-white max-w-xs truncate">
                      <div className="flex items-center space-x-2.5">
                        <div className="truncate">
                          <p className="truncate font-semibold text-white hover:text-brand-400 transition cursor-pointer" onClick={() => setPreviewVideo(v)}>
                            {v.file_name}
                          </p>
                          <div className="flex items-center space-x-2 mt-0.5">
                            <span className="text-[10px] text-studio-500 font-mono truncate">{v.id}</span>
                            {thumbStatus === 'completed' && (
                              <span className="text-[9px] text-emerald-400/90 font-medium bg-emerald-500/10 px-1 rounded">
                                Thumb ready
                              </span>
                            )}
                          </div>
                        </div>
                      </div>
                    </td>

                    {/* Resolution & FPS */}
                    <td className="py-3 px-4 whitespace-nowrap text-studio-300">
                      <div className="flex items-center space-x-1.5">
                        <Film className="w-3.5 h-3.5 text-studio-500" />
                        <span>
                          {v.width}x{v.height} {v.fps > 0 ? `@ ${v.fps}fps` : ''}
                        </span>
                      </div>
                    </td>

                    {/* Duration */}
                    <td className="py-3 px-4 whitespace-nowrap text-studio-300">
                      <div className="flex items-center space-x-1.5">
                        <Clock className="w-3.5 h-3.5 text-studio-500" />
                        <span>{formatDuration(v.duration_seconds)}</span>
                      </div>
                    </td>

                    {/* Codecs */}
                    <td className="py-3 px-4 whitespace-nowrap text-studio-400">
                      <span className="font-mono text-[11px] bg-studio-950 px-2 py-1 rounded border border-studio-800">
                        {v.video_codec || 'video'} / {v.audio_codec || 'no audio'}
                      </span>
                    </td>

                    {/* Size */}
                    <td className="py-3 px-4 whitespace-nowrap text-studio-300">
                      <div className="flex items-center space-x-1.5">
                        <HardDrive className="w-3.5 h-3.5 text-studio-500" />
                        <span>{formatBytes(v.file_size_bytes)}</span>
                      </div>
                    </td>

                    {/* Status Badge */}
                    <td className="py-3 px-4 whitespace-nowrap">
                      {v.status === 'ready' ? (
                        <span className="inline-flex items-center space-x-1 px-2.5 py-0.5 rounded-full text-[11px] font-medium bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                          <CheckCircle2 className="w-3 h-3" />
                          <span>Ready</span>
                        </span>
                      ) : (
                        <span className="inline-flex items-center space-x-1 px-2.5 py-0.5 rounded-full text-[11px] font-medium bg-amber-500/10 text-amber-400 border border-amber-500/20">
                          <span>{v.status}</span>
                        </span>
                      )}
                    </td>

                    {/* Imported Date */}
                    <td className="py-3 px-4 whitespace-nowrap text-studio-400 text-[11px]">
                      <div className="flex items-center space-x-1.5">
                        <Calendar className="w-3.5 h-3.5 text-studio-500" />
                        <span>{formatDate(v.created_at)}</span>
                      </div>
                    </td>

                    {/* Actions */}
                    <td className="py-3 px-4 whitespace-nowrap text-right">
                      <div className="flex items-center justify-end space-x-2">
                        {/* Regenerate Thumbnail Button */}
                        <button
                          onClick={() => handleRegenerate(v.id)}
                          disabled={regeneratingId === v.id || thumbStatus === 'processing'}
                          title="Regenerate Video Thumbnail"
                          className="p-1.5 rounded-lg bg-studio-800 text-studio-400 hover:text-brand-400 hover:bg-studio-700/80 transition disabled:opacity-50"
                        >
                          <RefreshCw className={`w-3.5 h-3.5 ${regeneratingId === v.id ? 'animate-spin text-brand-400' : ''}`} />
                        </button>

                        {/* Delete Button */}
                        <button
                          onClick={() => handleDelete(v.id)}
                          disabled={deletingId === v.id}
                          title="Delete Media Asset"
                          className="p-1.5 rounded-lg bg-studio-800 text-studio-400 hover:text-red-400 hover:bg-red-500/10 transition disabled:opacity-50"
                        >
                          {deletingId === v.id ? (
                            <Loader2 className="w-3.5 h-3.5 animate-spin text-red-400" />
                          ) : (
                            <Trash2 className="w-3.5 h-3.5" />
                          )}
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* Thumbnail Preview Modal */}
      {previewVideo && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm animate-in fade-in duration-150">
          <div className="relative w-full max-w-2xl bg-studio-900 border border-studio-800 rounded-2xl overflow-hidden shadow-2xl space-y-4 p-6">
            <div className="flex items-center justify-between border-b border-studio-800 pb-3">
              <div className="flex items-center space-x-2">
                <ImageIcon className="w-5 h-5 text-brand-500" />
                <h3 className="text-base font-semibold text-white truncate max-w-md">
                  {previewVideo.file_name}
                </h3>
              </div>
              <button
                onClick={() => setPreviewVideo(null)}
                className="p-1.5 rounded-lg bg-studio-800 text-studio-400 hover:text-white transition"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            {/* Modal Image Display */}
            <div className="relative rounded-xl overflow-hidden bg-black/60 aspect-video flex items-center justify-center border border-studio-800">
              <img
                src={getThumbnailUrl(previewVideo.id)}
                alt={previewVideo.file_name}
                className="w-full h-full object-contain"
              />
            </div>

            {/* Modal Metadata & Actions */}
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pt-2 text-xs text-studio-400">
              <div className="space-y-1">
                <p className="text-white font-medium">
                  Video: {previewVideo.width}x{previewVideo.height} @ {previewVideo.fps}fps • {formatDuration(previewVideo.duration_seconds)}
                </p>
                {previewMetadata && previewMetadata.width && previewMetadata.height ? (
                  <p className="text-emerald-400 font-medium text-[11px]">
                    Thumbnail: {previewMetadata.width}x{previewMetadata.height}px • {formatBytes(previewMetadata.file_size_bytes || 0)}
                  </p>
                ) : (
                  <p className="text-studio-500 text-[11px]">Thumbnail: Actual dimensions loading...</p>
                )}
                <p className="font-mono text-[11px] text-studio-500">
                  ID: {previewVideo.id}
                </p>
              </div>

              <div className="flex items-center space-x-2">
                <button
                  onClick={() => {
                    handleRegenerate(previewVideo.id);
                  }}
                  disabled={regeneratingId === previewVideo.id}
                  className="flex items-center space-x-1.5 px-3 py-1.5 rounded-xl bg-studio-800 hover:bg-studio-700 text-white font-medium transition disabled:opacity-50"
                >
                  <RefreshCw className={`w-3.5 h-3.5 ${regeneratingId === previewVideo.id ? 'animate-spin text-brand-400' : ''}`} />
                  <span>{regeneratingId === previewVideo.id ? 'Regenerating...' : 'Regenerate'}</span>
                </button>
                <button
                  onClick={() => setPreviewVideo(null)}
                  className="px-3 py-1.5 rounded-xl bg-brand-500 hover:bg-brand-600 text-white font-semibold transition"
                >
                  Close
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
