import React, { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  UploadCloud,
  Film,
  HardDrive,
  Clock,
  Search,
  RefreshCw,
} from 'lucide-react';
import { fetchMedia, fetchWorkspaces, deleteMedia, regenerateThumbnail, reconcileThumbnails } from '../../api/client';
import { VideoUploadModal } from './VideoUploadModal';
import { MediaTable } from './MediaTable';

export const ImportedVideosView: React.FC = () => {
  const queryClient = useQueryClient();
  const [selectedWorkspaceId, setSelectedWorkspaceId] = useState<string>('');
  const [searchQuery, setSearchQuery] = useState('');
  const [isUploadModalOpen, setIsUploadModalOpen] = useState(false);

  // 1. Fetch available workspaces
  const { data: workspaces = [] } = useQuery({
    queryKey: ['workspaces'],
    queryFn: fetchWorkspaces,
  });

  // Default to first workspace if not selected
  React.useEffect(() => {
    if (workspaces.length > 0 && !selectedWorkspaceId) {
      setSelectedWorkspaceId(workspaces[0].id);
    }
  }, [workspaces, selectedWorkspaceId]);

  // 2. Fetch imported videos for selected workspace
  const {
    data: mediaData,
    isLoading: isMediaLoading,
  } = useQuery({
    queryKey: ['media', selectedWorkspaceId],
    queryFn: () => fetchMedia(selectedWorkspaceId || undefined),
    enabled: true,
  });

  const videos = mediaData?.items || [];

  // Filter videos by search query
  const filteredVideos = videos.filter((v) =>
    v.file_name.toLowerCase().includes(searchQuery.toLowerCase())
  );

  // Compute workspace metrics
  const totalDurationSec = videos.reduce((acc, v) => acc + (v.duration_seconds || 0), 0);
  const totalSizeBytes = videos.reduce((acc, v) => acc + (v.file_size_bytes || 0), 0);

  const formatTotalDuration = (seconds: number) => {
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    if (h > 0) return `${h}h ${m}m`;
    return `${m}m ${Math.floor(seconds % 60)}s`;
  };

  const formatTotalSize = (bytes: number) => {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return `${(bytes / Math.pow(k, i)).toFixed(2)} ${sizes[i]}`;
  };

  const handleDelete = async (videoId: string) => {
    await deleteMedia(videoId);
    queryClient.invalidateQueries({ queryKey: ['media', selectedWorkspaceId] });
  };

  const [isReconciling, setIsReconciling] = useState(false);

  const handleRegenerateThumbnail = async (videoId: string) => {
    await regenerateThumbnail(videoId);
    queryClient.invalidateQueries({ queryKey: ['media', selectedWorkspaceId] });
    queryClient.invalidateQueries({ queryKey: ['jobs'] });
  };

  const handleReconcileThumbnails = async () => {
    setIsReconciling(true);
    try {
      await reconcileThumbnails(selectedWorkspaceId || undefined);
      queryClient.invalidateQueries({ queryKey: ['media', selectedWorkspaceId] });
      queryClient.invalidateQueries({ queryKey: ['jobs'] });
    } finally {
      setIsReconciling(false);
    }
  };

  const handleUploadSuccess = () => {
    queryClient.invalidateQueries({ queryKey: ['media', selectedWorkspaceId] });
  };

  return (
    <div className="space-y-6">
      {/* View Header with Workspace Selector & Upload Button */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-2 border-b border-studio-800">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-white flex items-center space-x-2.5">
            <Film className="w-6 h-6 text-brand-500" />
            <span>Imported Videos</span>
          </h1>
          <p className="text-sm text-studio-400 mt-1">
            Phase 2A — Streamed chunk upload, FFprobe stream validation & local storage persistence
          </p>
        </div>

        <div className="flex items-center space-x-3">
          {/* Workspace Filter Dropdown */}
          <div className="flex items-center space-x-2 bg-studio-900 border border-studio-800 rounded-xl px-3 py-1.5">
            <span className="text-xs text-studio-400 font-medium">Workspace:</span>
            <select
              value={selectedWorkspaceId}
              onChange={(e) => setSelectedWorkspaceId(e.target.value)}
              className="bg-transparent text-xs text-white font-medium focus:outline-none cursor-pointer"
            >
              {workspaces.map((ws) => (
                <option key={ws.id} value={ws.id} className="bg-studio-900 text-white">
                  {ws.name}
                </option>
              ))}
            </select>
          </div>

          {/* Reconcile Thumbnails Button */}
          <button
            onClick={handleReconcileThumbnails}
            disabled={isReconciling}
            title="Reconcile missing or pending thumbnails"
            className="flex items-center space-x-1.5 px-3 py-2 rounded-xl bg-studio-800 hover:bg-studio-700 text-studio-300 hover:text-white text-xs font-medium transition disabled:opacity-50"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isReconciling ? 'animate-spin text-brand-400' : ''}`} />
            <span>{isReconciling ? 'Reconciling...' : 'Reconcile Thumbnails'}</span>
          </button>

          {/* Import Video Button */}
          <button
            onClick={() => setIsUploadModalOpen(true)}
            className="flex items-center space-x-2 px-4 py-2 bg-brand-500 hover:bg-brand-600 text-white text-xs font-semibold rounded-xl shadow-lg shadow-brand-500/20 transition"
          >
            <UploadCloud className="w-4 h-4" />
            <span>Import Video</span>
          </button>
        </div>
      </div>

      {/* Metrics Row */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* Total Assets */}
        <div className="bg-studio-900 border border-studio-800 rounded-xl p-4 flex items-center space-x-3.5 shadow-md">
          <div className="p-3 rounded-xl bg-brand-500/10 text-brand-500 border border-brand-500/20">
            <Film className="w-5 h-5" />
          </div>
          <div>
            <p className="text-xs text-studio-400 font-medium">Imported Media Assets</p>
            <p className="text-xl font-bold text-white mt-0.5">{videos.length} videos</p>
          </div>
        </div>

        {/* Total Duration */}
        <div className="bg-studio-900 border border-studio-800 rounded-xl p-4 flex items-center space-x-3.5 shadow-md">
          <div className="p-3 rounded-xl bg-blue-500/10 text-blue-400 border border-blue-500/20">
            <Clock className="w-5 h-5" />
          </div>
          <div>
            <p className="text-xs text-studio-400 font-medium">Total Media Duration</p>
            <p className="text-xl font-bold text-white mt-0.5">{formatTotalDuration(totalDurationSec)}</p>
          </div>
        </div>

        {/* Total Size */}
        <div className="bg-studio-900 border border-studio-800 rounded-xl p-4 flex items-center space-x-3.5 shadow-md">
          <div className="p-3 rounded-xl bg-purple-500/10 text-purple-400 border border-purple-500/20">
            <HardDrive className="w-5 h-5" />
          </div>
          <div>
            <p className="text-xs text-studio-400 font-medium">Total Local Disk Storage</p>
            <p className="text-xl font-bold text-white mt-0.5">{formatTotalSize(totalSizeBytes)}</p>
          </div>
        </div>
      </div>

      {/* Search & Filter Bar */}
      <div className="flex items-center justify-between gap-4">
        <div className="relative flex-1 max-w-md">
          <Search className="w-4 h-4 text-studio-400 absolute left-3.5 top-1/2 -translate-y-1/2" />
          <input
            type="text"
            placeholder="Search imported videos by filename..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full bg-studio-900 border border-studio-800 rounded-xl pl-10 pr-4 py-2 text-xs text-white placeholder-studio-500 focus:outline-none focus:border-brand-500 transition"
          />
        </div>
        <div className="text-xs text-studio-400">
          Showing {filteredVideos.length} of {videos.length} files
        </div>
      </div>

      {/* Media Table */}
      <MediaTable
        videos={filteredVideos}
        isLoading={isMediaLoading}
        onDeleteVideo={handleDelete}
        onRegenerateThumbnail={handleRegenerateThumbnail}
      />

      {/* Upload Modal */}
      <VideoUploadModal
        isOpen={isUploadModalOpen}
        onClose={() => setIsUploadModalOpen(false)}
        onUploadSuccess={handleUploadSuccess}
        defaultWorkspaceId={selectedWorkspaceId}
      />
    </div>
  );
};
