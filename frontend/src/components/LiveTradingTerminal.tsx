import React, { useEffect, useState } from 'react';
import {
  closeLivePosition,
  startLivePaper,
  stopLivePaper,
  updateLiveStops,
} from '../services/api';
import { LiveTradingTabs } from './LiveTradingTabs';
import { LiveHeader } from './terminal/LiveHeader';
import { LiveMetricsRibbon } from './terminal/LiveMetricsRibbon';
import { LiveChart } from './terminal/LiveChart';
import { ActivePositionCard } from './terminal/ActivePositionCard';
import { SessionConfigCard } from './terminal/SessionConfigCard';
import { LiveWarningModal } from './terminal/LiveWarningModal';
import { useLiveTradingSession } from './terminal/useLiveTradingSession';

interface LiveTradingTerminalProps {
  supportedRobots?: string[];
  /** Session shown and controlled here; null = the "new session" form. */
  sessionId?: string | null;
  /** Called with the new id after Start, and with null after Stop. */
  onSessionChange?: (sessionId: string | null) => void;
}

export const LiveTradingTerminal: React.FC<LiveTradingTerminalProps> = ({
  supportedRobots = ['regime', 'ema', 'adaptive_ema'],
  sessionId = null,
  onSessionChange,
}) => {
  const [sessionName, setSessionName] = useState('');
  const [sessionNotes, setSessionNotes] = useState('');
  // Session & Config state
  const [mode, setMode] = useState<'paper' | 'live_guarded'>('paper');
  const [symbol, setSymbol] = useState('BTCUSDT');
  const [interval, setIntervalVal] = useState('1m');
  const [robot, setRobot] = useState('regime');
  const [autoTrade, setAutoTrade] = useState(true);
  const [startingEquity, setStartingEquity] = useState('10000');
  const [riskPct, setRiskPct] = useState('0.01');
  const [stopPct, setStopPct] = useState('0.015');
  const [tpMultiple, setTpMultiple] = useState('2.0');

  // Runtime State from Hook
  const {
    state,
    isConnected,
    statusMsg,
    setStatusMsg,
    lastBar,
    editSl,
    setEditSl,
    editTp,
    setEditTp,
    reloadState,
  } = useLiveTradingSession(sessionId);

  const [actionError, setActionError] = useState<string | null>(null);
  const [activeBottomTab, setActiveBottomTab] = useState<'position' | 'fills' | 'risk' | 'decision_logs'>('position');
  const [showLiveWarningModal, setShowLiveWarningModal] = useState(false);

  // While a session runs, sync config from server
  const activeConfig = state?.is_active ? state.config : null;
  useEffect(() => {
    if (!activeConfig) return;
    setSymbol(activeConfig.symbol);
    setIntervalVal(activeConfig.interval);
    setRobot(activeConfig.robot);
    setStartingEquity(activeConfig.starting_equity);
    setRiskPct(activeConfig.risk_per_trade);
    setStopPct(activeConfig.stop_pct);
    setTpMultiple(activeConfig.take_profit_multiple);
    setAutoTrade(activeConfig.auto_trade);
    setSessionName(state?.name ?? activeConfig.name ?? '');
    setSessionNotes(state?.notes ?? activeConfig.notes ?? '');
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    activeConfig?.symbol,
    activeConfig?.interval,
    activeConfig?.robot,
    activeConfig?.starting_equity,
    activeConfig?.risk_per_trade,
    activeConfig?.stop_pct,
    activeConfig?.take_profit_multiple,
    activeConfig?.auto_trade,
    activeConfig?.name,
    activeConfig?.notes,
    state?.name,
    state?.notes,
  ]);

  // Actions
  const handleStartSession = async () => {
    setActionError(null);
    try {
      const res = await startLivePaper({
        name: sessionName.trim(),
        notes: sessionNotes.trim(),
        symbol,
        interval,
        robot,
        starting_equity: startingEquity,
        risk_per_trade: riskPct,
        stop_pct: stopPct,
        take_profit_multiple: tpMultiple,
        mode,
        auto_trade: autoTrade,
      });
      if (res.status === 'started') {
        setStatusMsg(`Active: ${res.name ?? symbol} (${robot})`);
        if (res.session_id) onSessionChange?.(res.session_id);
      } else {
        setActionError(res.message || 'Failed to start session');
      }
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Error starting live paper session');
    }
  };

  const handleStopSession = async () => {
    if (!sessionId) return;
    const label = state?.name || sessionId;
    const confirmed = window.confirm(
      `Stop "${label}" for good?\n\nA stopped session is final: it is not resumed after a ` +
        'restart and is not restarted from the portfolio file. Use Pause to only halt new entries.',
    );
    if (!confirmed) return;
    setActionError(null);
    try {
      await stopLivePaper(sessionId);
      setStatusMsg('Session stopped');
      reloadState();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Error stopping session');
    }
  };

  const handleClosePosition = async () => {
    setActionError(null);
    try {
      if (!sessionId) return;
      const res = await closeLivePosition(sessionId);
      setStatusMsg(res.message || 'Position closed');
      reloadState();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Error closing position');
    }
  };

  const handleUpdateStops = async () => {
    setActionError(null);
    try {
      if (!sessionId) return;
      const res = await updateLiveStops(sessionId, {
        stop_loss: editSl ? editSl : null,
        take_profit: editTp ? editTp : null,
      });
      setStatusMsg(res.message || 'Stops updated');
      reloadState();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Error updating stops');
    }
  };

  const handleModeSwitch = (targetMode: 'paper' | 'live_guarded') => {
    if (targetMode === 'live_guarded') {
      setShowLiveWarningModal(true);
    } else {
      setMode('paper');
    }
  };

  return (
    <div className="flex flex-col gap-5">
      {/* Top Header & Mode Switcher */}
      <LiveHeader
        mode={mode}
        onModeSwitch={handleModeSwitch}
        isConnected={isConnected}
        isActive={state?.is_active}
        onStartSession={handleStartSession}
        onStopSession={handleStopSession}
        actionError={actionError}
      />

      {/* Account Metrics Ribbon */}
      <LiveMetricsRibbon
        state={state}
        startingEquity={startingEquity}
        symbol={symbol}
      />

      {/* Main Grid: Chart + Controls */}
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-5">
        <LiveChart
          symbol={symbol}
          setSymbol={setSymbol}
          interval={interval}
          setIntervalVal={setIntervalVal}
          robot={robot}
          mode={mode}
          statusMsg={statusMsg}
          recentBars={state?.recent_bars}
          lastBar={lastBar}
          position={state?.position}
          isActive={state?.is_active}
        />

        {/* Sidebar Controls Column (1 col) */}
        <div className="flex flex-col gap-4">
          <ActivePositionCard
            position={state?.position}
            editSl={editSl}
            setEditSl={setEditSl}
            editTp={editTp}
            setEditTp={setEditTp}
            onUpdateStops={handleUpdateStops}
            onClosePosition={handleClosePosition}
          />

          <SessionConfigCard
            sessionName={sessionName}
            setSessionName={setSessionName}
            sessionNotes={sessionNotes}
            setSessionNotes={setSessionNotes}
            robot={robot}
            setRobot={setRobot}
            supportedRobots={supportedRobots}
            startingEquity={startingEquity}
            setStartingEquity={setStartingEquity}
            riskPct={riskPct}
            setRiskPct={setRiskPct}
            stopPct={stopPct}
            setStopPct={setStopPct}
            tpMultiple={tpMultiple}
            setTpMultiple={setTpMultiple}
            autoTrade={autoTrade}
            setAutoTrade={setAutoTrade}
            isActive={state?.is_active}
            symbol={symbol}
          />
        </div>
      </div>

      {/* Bottom Tabs Drawer: Positions, Order History, Risk Breaches */}
      <LiveTradingTabs
        activeTab={activeBottomTab}
        onTabChange={setActiveBottomTab}
        state={state}
        sessionId={sessionId}
      />

      {/* Safety Modal for Live Trading confirmation */}
      <LiveWarningModal
        isOpen={showLiveWarningModal}
        onConfirm={() => {
          setMode('live_guarded');
          setShowLiveWarningModal(false);
        }}
        onCancel={() => setShowLiveWarningModal(false)}
      />
    </div>
  );
};
