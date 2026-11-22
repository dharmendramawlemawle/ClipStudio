import React, { useState } from 'react';
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
} from 'lucide-react';
import { ImportedVideo } from '../../types';

interface MediaTableProps {
  videos: ImportedVideo[];
  isLoading: boolean;
  onDeleteVideo: (videoId: string) => Promise<void>;
}

export const MediaTable: React.FC<MediaTableProps> = ({
  videos,
  isLoading,
  onDeleteVideo,
}) => {
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

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
    } catch (err: any) {
      setDeleteError(err.message || 'Failed to delete media asset.');
    } finally {
      setDeletingId(null);
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

      <div className="bg-studio-900 border border-studio-800 rounded-2xl overflow-hidden shadow-xl">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="bg-studio-950/80 border-b border-studio-800 text-studio-400 font-medium uppercase tracking-wider text-[11px]">
              <tr>
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
              {videos.map((v) => (
                <tr key={v.id} className="hover:bg-studio-850/50 transition">
                  {/* File Name */}
                  <td className="py-3 px-4 font-medium text-white max-w-xs truncate">
                    <div className="flex items-center space-x-2.5">
                      <div className="p-2 rounded-lg bg-brand-500/10 text-brand-500 shrink-0">
                        <FileVideo className="w-4 h-4" />
                      </div>
                      <div className="truncate">
                        <p className="truncate font-semibold">{v.file_name}</p>
                        <p className="text-[10px] text-studio-500 font-mono mt-0.5 truncate">{v.id}</p>
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
                    <button
                      onClick={() => handleDelete(v.id)}
                      disabled={deletingId === v.id}
                      className="p-1.5 text-studio-400 hover:text-red-400 hover:bg-studio-800 rounded-lg transition disabled:opacity-50"
                      title="Delete video"
                    >
                      {deletingId === v.id ? (
                        <Loader2 className="w-4 h-4 animate-spin text-red-400" />
                      ) : (
                        <Trash2 className="w-4 h-4" />
                      )}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};
