import React from 'react';
import { Film, Radio, Activity, RefreshCw } from 'lucide-react';
import { HealthResponse } from '../types';
import { WSStatus } from '../hooks/useWebSocket';

interface HeaderProps {
  health: HealthResponse | null;
  healthLoading: boolean;
  wsStatus: WSStatus;
  onRefreshHealth: () => void;
  onReconnectWS: () => void;
}

export const Header: React.FC<HeaderProps> = ({
  health,
  healthLoading,
  wsStatus,
  onRefreshHealth,
  onReconnectWS,
}) => {
  const isHealthy = health?.status === 'ok';

  return (
    <header className="h-16 border-b border-studio-800 bg-studio-900/90 backdrop-blur px-6 flex items-center justify-between sticky top-0 z-40">
      {/* Brand & Mode */}
      <div className="flex items-center space-x-3">
        <div className="w-9 h-9 rounded-lg bg-gradient-to-tr from-brand-600 to-brand-500 flex items-center justify-center shadow-lg shadow-brand-500/20">
          <Film className="w-5 h-5 text-black" />
        </div>
        <div>
          <div className="flex items-center space-x-2">
            <span className="font-bold text-lg tracking-tight text-white">ClipStudio</span>
            <span className="text-[10px] uppercase font-semibold bg-studio-800 text-brand-500 px-2 py-0.5 rounded border border-brand-500/30">
              Phase 1 Dev
            </span>
          </div>
          <p className="text-xs text-studio-400">Independent Local-First Creator Workspace</p>
        </div>
      </div>

      {/* Connectivity & Health Badges */}
      <div className="flex items-center space-x-4">
        {/* Backend REST Health Status */}
        <div className="flex items-center space-x-2 bg-studio-850 border border-studio-800 px-3 py-1.5 rounded-md text-xs">
          <Activity className="w-3.5 h-3.5 text-studio-400" />
          <span className="text-studio-400 font-medium">Backend:</span>
          {healthLoading ? (
            <span className="text-studio-400 animate-pulse">Checking...</span>
          ) : isHealthy ? (
            <span className="flex items-center text-brand-500 font-semibold">
              <span className="w-2 h-2 rounded-full bg-brand-500 mr-1.5 animate-pulse" />
              Online (v{health?.version})
            </span>
          ) : (
            <span className="flex items-center text-red-400 font-semibold">
              <span className="w-2 h-2 rounded-full bg-red-400 mr-1.5" />
              Offline
            </span>
          )}
          <button
            onClick={onRefreshHealth}
            title="Refresh backend status"
            className="text-studio-400 hover:text-studio-100 transition ml-1"
          >
            <RefreshCw className="w-3 h-3" />
          </button>
        </div>

        {/* WebSocket Real-time Status */}
        <div className="flex items-center space-x-2 bg-studio-850 border border-studio-800 px-3 py-1.5 rounded-md text-xs">
          <Radio className="w-3.5 h-3.5 text-studio-400" />
          <span className="text-studio-400 font-medium">WebSocket:</span>
          {wsStatus === 'connected' ? (
            <span className="flex items-center text-brand-500 font-semibold">
              <span className="w-2 h-2 rounded-full bg-brand-500 mr-1.5" />
              Live
            </span>
          ) : wsStatus === 'connecting' ? (
            <span className="flex items-center text-yellow-400 font-semibold">
              <span className="w-2 h-2 rounded-full bg-yellow-400 mr-1.5 animate-ping" />
              Connecting
            </span>
          ) : (
            <span className="flex items-center text-zinc-400 font-semibold">
              <span className="w-2 h-2 rounded-full bg-zinc-500 mr-1.5" />
              Disconnected
            </span>
          )}
          {wsStatus !== 'connected' && (
            <button
              onClick={onReconnectWS}
              className="text-xs text-brand-500 hover:underline font-medium ml-1"
            >
              Reconnect
            </button>
          )}
        </div>
      </div>
    </header>
  );
};
