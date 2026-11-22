import React, { useState, useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  UploadCloud,
  X,
  FileVideo,
  CheckCircle2,
  Loader2,
  AlertCircle,
  Copy,
} from 'lucide-react';
import { fetchWorkspaces, initiateUpload, uploadChunk, completeUpload } from '../../api/client';
import { ImportedVideo } from '../../types';

interface VideoUploadModalProps {
  isOpen: boolean;
  onClose: () => void;
  onUploadSuccess: (video: ImportedVideo) => void;
  defaultWorkspaceId?: string;
}

export const VideoUploadModal: React.FC<VideoUploadModalProps> = ({
  isOpen,
  onClose,
  onUploadSuccess,
  defaultWorkspaceId,
}) => {
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [workspaceId, setWorkspaceId] = useState<string>(defaultWorkspaceId || '');
  const [isDragging, setIsDragging] = useState(false);

  // Upload progress states
  const [isUploading, setIsUploading] = useState(false);
  const [progressPercent, setProgressPercent] = useState(0);
  const [uploadedBytes, setUploadedBytes] = useState(0);
  const [transferSpeed, setTransferSpeed] = useState<string>('');
  const [currentStage, setCurrentStage] = useState<'idle' | 'uploading' | 'validating' | 'completed' | 'duplicate'>('idle');
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [duplicateInfo, setDuplicateInfo] = useState<{ uploadId: string; duplicateId: string; message: string } | null>(null);

  const abortControllerRef = useRef<AbortController | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Fetch workspaces for selector
  const { data: workspaces = [] } = useQuery({
    queryKey: ['workspaces'],
    queryFn: fetchWorkspaces,
    enabled: isOpen,
  });

  // Reset modal state on open
  React.useEffect(() => {
    if (isOpen) {
      setSelectedFile(null);
      setIsUploading(false);
      setProgressPercent(0);
      setUploadedBytes(0);
      setTransferSpeed('');
      setCurrentStage('idle');
      setErrorMessage(null);
      setDuplicateInfo(null);
    }
  }, [isOpen]);

  // Default to first workspace if not set
  React.useEffect(() => {
    if (workspaces.length > 0 && !workspaceId) {
      setWorkspaceId(workspaces[0].id);
    }
  }, [workspaces, workspaceId]);

  if (!isOpen) return null;

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = () => {
    setIsDragging(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      const file = e.dataTransfer.files[0];
      setSelectedFile(file);
      setErrorMessage(null);
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      setSelectedFile(e.target.files[0]);
      setErrorMessage(null);
    }
  };

  const formatBytes = (bytes: number) => {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return `${(bytes / Math.pow(k, i)).toFixed(2)} ${sizes[i]}`;
  };

  const handleCancelUpload = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    setIsUploading(false);
    setCurrentStage('idle');
    setProgressPercent(0);
    setUploadedBytes(0);
    setErrorMessage('Upload cancelled by user.');
  };

  const startUpload = async (confirmDuplicate: boolean = false) => {
    if (!selectedFile || !workspaceId) {
      setErrorMessage('Please select a video file and target workspace.');
      return;
    }

    setErrorMessage(null);
    setIsUploading(true);
    setCurrentStage('uploading');
    setProgressPercent(0);
    setUploadedBytes(0);
    setTransferSpeed('');

    const abortController = new AbortController();
    abortControllerRef.current = abortController;

    try {
      // 1. Initiate upload session
      const session = await initiateUpload(workspaceId, selectedFile.name, selectedFile.size);
      const uploadId = session.id;

      // 2. Chunk streaming parameters (1 MB per chunk)
      const chunkSize = 1024 * 1024;
      const totalSize = selectedFile.size;

      let offset = 0;
      let chunkIndex = 0;
      const startTime = Date.now();

      while (offset < totalSize) {
        if (abortController.signal.aborted) {
          return;
        }

        const chunkEnd = Math.min(offset + chunkSize, totalSize);
        const chunkBlob = selectedFile.slice(offset, chunkEnd);

        await uploadChunk(uploadId, chunkIndex, offset, chunkBlob, abortController.signal);

        offset = chunkEnd;
        chunkIndex++;

        setUploadedBytes(offset);
        const percent = Math.min(Math.round((offset / totalSize) * 100), 99);
        setProgressPercent(percent);

        // Calculate transfer speed
        const elapsedSec = (Date.now() - startTime) / 1000;
        if (elapsedSec > 0.5) {
          const speedBytesPerSec = offset / elapsedSec;
          setTransferSpeed(`${(speedBytesPerSec / (1024 * 1024)).toFixed(1)} MB/s`);
        }
      }

      // 3. Complete and Validate Media via FFprobe
      setCurrentStage('validating');
      const completeRes = await completeUpload(uploadId, confirmDuplicate);

      if (completeRes.status === 'duplicate_detected') {
        setCurrentStage('duplicate');
        setDuplicateInfo({
          uploadId,
          duplicateId: completeRes.duplicate_video_id || '',
          message: completeRes.message || 'Identical content already exists.',
        });
        setIsUploading(false);
        return;
      }

      if (completeRes.video) {
        setProgressPercent(100);
        setCurrentStage('completed');
        setIsUploading(false);
        setTimeout(() => {
          onUploadSuccess(completeRes.video!);
          onClose();
        }, 1200);
      }
    } catch (err: any) {
      if (err.name === 'AbortError') {
        setErrorMessage('Upload was cancelled.');
      } else {
        setErrorMessage(err.message || 'An unexpected error occurred during upload.');
      }
      setIsUploading(false);
      setCurrentStage('idle');
    }
  };

  const handleConfirmDuplicate = async () => {
    if (!duplicateInfo) return;
    setIsUploading(true);
    setCurrentStage('validating');
    try {
      const completeRes = await completeUpload(duplicateInfo.uploadId, true);
      if (completeRes.video) {
        setProgressPercent(100);
        setCurrentStage('completed');
        setIsUploading(false);
        setTimeout(() => {
          onUploadSuccess(completeRes.video!);
          onClose();
        }, 800);
      }
    } catch (err: any) {
      setErrorMessage(err.message || 'Duplicate confirmation failed.');
      setIsUploading(false);
      setCurrentStage('idle');
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4 animate-in fade-in">
      <div className="bg-studio-900 border border-studio-800 rounded-2xl w-full max-w-lg shadow-2xl overflow-hidden flex flex-col">
        {/* Modal Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-studio-800 bg-studio-900/90">
          <div className="flex items-center space-x-2.5">
            <div className="p-2 rounded-lg bg-brand-500/10 text-brand-500 border border-brand-500/20">
              <UploadCloud className="w-5 h-5" />
            </div>
            <div>
              <h2 className="text-base font-semibold text-white">Import Local Video</h2>
              <p className="text-xs text-studio-400">Streamed chunked upload with FFprobe validation</p>
            </div>
          </div>
          <button
            onClick={onClose}
            disabled={isUploading}
            className="text-studio-400 hover:text-white transition p-1.5 rounded-lg hover:bg-studio-800 disabled:opacity-50"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Modal Body */}
        <div className="p-6 space-y-5">
          {/* Workspace Selector */}
          <div>
            <label className="block text-xs font-medium text-studio-300 mb-1.5">Target Workspace</label>
            <select
              value={workspaceId}
              onChange={(e) => setWorkspaceId(e.target.value)}
              disabled={isUploading}
              className="w-full bg-studio-950 border border-studio-800 rounded-xl px-3.5 py-2.5 text-sm text-white focus:outline-none focus:border-brand-500 transition disabled:opacity-50"
            >
              {workspaces.map((ws) => (
                <option key={ws.id} value={ws.id}>
                  {ws.name} ({ws.local_storage_path})
                </option>
              ))}
            </select>
          </div>

          {/* Drag & Drop Zone */}
          {!selectedFile && (
            <div
              onDragOver={handleDragOver}
              onDragLeave={handleDragLeave}
              onDrop={handleDrop}
              onClick={() => fileInputRef.current?.click()}
              className={`border-2 border-dashed rounded-xl p-8 flex flex-col items-center justify-center cursor-pointer transition ${
                isDragging
                  ? 'border-brand-500 bg-brand-500/5'
                  : 'border-studio-700 hover:border-studio-600 bg-studio-950/60'
              }`}
            >
              <input
                ref={fileInputRef}
                type="file"
                accept=".mp4,.mov,.mkv,.webm,.avi,.m4v"
                onChange={handleFileChange}
                className="hidden"
              />
              <FileVideo className="w-10 h-10 text-studio-400 mb-3" />
              <p className="text-sm font-medium text-white mb-1">Drag and drop your video file here</p>
              <p className="text-xs text-studio-400 mb-4">Supports MP4, MOV, MKV, WebM, AVI (up to 5 GB)</p>
              <span className="text-xs font-semibold px-3 py-1.5 bg-studio-800 hover:bg-studio-700 text-studio-200 rounded-lg transition">
                Browse Files
              </span>
            </div>
          )}

          {/* Selected File Card */}
          {selectedFile && (
            <div className="bg-studio-950 border border-studio-800 rounded-xl p-4 flex items-center justify-between">
              <div className="flex items-center space-x-3 truncate">
                <div className="p-2.5 rounded-lg bg-brand-500/10 text-brand-500 shrink-0">
                  <FileVideo className="w-6 h-6" />
                </div>
                <div className="truncate">
                  <p className="text-sm font-medium text-white truncate">{selectedFile.name}</p>
                  <p className="text-xs text-studio-400 mt-0.5">{formatBytes(selectedFile.size)}</p>
                </div>
              </div>
              {!isUploading && currentStage !== 'completed' && (
                <button
                  onClick={() => setSelectedFile(null)}
                  className="text-xs text-studio-400 hover:text-red-400 transition ml-3 px-2 py-1 rounded hover:bg-studio-850"
                >
                  Change
                </button>
              )}
            </div>
          )}

          {/* Upload Progress Bar */}
          {isUploading && (
            <div className="space-y-2 bg-studio-950 border border-studio-800 rounded-xl p-4">
              <div className="flex items-center justify-between text-xs">
                <span className="text-studio-300 font-medium flex items-center space-x-2">
                  {currentStage === 'uploading' && <Loader2 className="w-3.5 h-3.5 animate-spin text-brand-500" />}
                  {currentStage === 'validating' && <Loader2 className="w-3.5 h-3.5 animate-spin text-yellow-400" />}
                  <span>
                    {currentStage === 'uploading' ? `Uploading (${transferSpeed || 'calculating...'})` : 'Probing with FFprobe...'}
                  </span>
                </span>
                <span className="font-semibold text-white">{progressPercent}%</span>
              </div>
              <div className="w-full bg-studio-800 h-2 rounded-full overflow-hidden">
                <div
                  className="bg-brand-500 h-full transition-all duration-200 rounded-full"
                  style={{ width: `${progressPercent}%` }}
                />
              </div>
              <div className="flex justify-between items-center text-[11px] text-studio-400 pt-1">
                <span>
                  {formatBytes(uploadedBytes)} / {formatBytes(selectedFile?.size || 0)}
                </span>
                <button
                  onClick={handleCancelUpload}
                  className="text-red-400 hover:text-red-300 font-medium transition"
                >
                  Cancel Upload
                </button>
              </div>
            </div>
          )}

          {/* Success Banner */}
          {currentStage === 'completed' && (
            <div className="bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 p-4 rounded-xl flex items-center space-x-3">
              <CheckCircle2 className="w-5 h-5 shrink-0" />
              <div className="text-xs">
                <p className="font-semibold">Media Verified & Stored!</p>
                <p className="text-emerald-300/80 mt-0.5">FFprobe streams verified and asset registered.</p>
              </div>
            </div>
          )}

          {/* Duplicate Detected Banner */}
          {currentStage === 'duplicate' && duplicateInfo && (
            <div className="bg-amber-500/10 border border-amber-500/20 text-amber-300 p-4 rounded-xl space-y-3">
              <div className="flex items-start space-x-3">
                <Copy className="w-5 h-5 text-amber-400 shrink-0 mt-0.5" />
                <div className="text-xs">
                  <p className="font-semibold text-white">Duplicate Video Content Detected</p>
                  <p className="text-amber-300/80 mt-1">{duplicateInfo.message}</p>
                </div>
              </div>
              <div className="flex items-center space-x-3 pt-1">
                <button
                  onClick={handleConfirmDuplicate}
                  className="flex-1 px-3 py-2 bg-amber-500 hover:bg-amber-600 text-black font-semibold rounded-lg text-xs transition"
                >
                  Import as New Reference
                </button>
                <button
                  onClick={onClose}
                  className="px-3 py-2 bg-studio-800 hover:bg-studio-700 text-studio-200 rounded-lg text-xs transition"
                >
                  Cancel
                </button>
              </div>
            </div>
          )}

          {/* Error Banner */}
          {errorMessage && (
            <div className="bg-red-500/10 border border-red-500/20 text-red-400 p-4 rounded-xl flex items-start space-x-3">
              <AlertCircle className="w-5 h-5 shrink-0 mt-0.5" />
              <div className="text-xs">
                <p className="font-semibold">Upload Failed</p>
                <p className="text-red-300/80 mt-1">{errorMessage}</p>
              </div>
            </div>
          )}
        </div>

        {/* Modal Footer */}
        <div className="px-6 py-4 border-t border-studio-800 bg-studio-900/90 flex justify-end space-x-3">
          <button
            onClick={onClose}
            disabled={isUploading}
            className="px-4 py-2 rounded-xl text-sm font-medium text-studio-300 hover:bg-studio-800 hover:text-white transition disabled:opacity-50"
          >
            Close
          </button>
          {!isUploading && currentStage !== 'completed' && currentStage !== 'duplicate' && (
            <button
              onClick={() => startUpload(false)}
              disabled={!selectedFile || !workspaceId}
              className="px-5 py-2 rounded-xl text-sm font-semibold bg-brand-500 hover:bg-brand-600 text-white shadow-lg shadow-brand-500/20 transition disabled:opacity-50 disabled:cursor-not-allowed flex items-center space-x-2"
            >
              <UploadCloud className="w-4 h-4" />
              <span>Start Upload</span>
            </button>
          )}
        </div>
      </div>
    </div>
  );
};
