import React from 'react';
import { AppProvider } from './context/AppContext';
import Header from './components/Header';
import MapView from './components/MapView';
import AgentStage from './components/AgentStage';
import TripInfo from './components/TripInfo';
import RecordButton from './components/RecordButton';
import TripOverlay from './components/TripOverlay';
import RideMoving from './components/RideMoving';
import RideArrived from './components/RideArrived';
import LoginPage from './components/LoginPage';
import DriverView from './components/DriverView';
import HomeView from './components/HomeView';
import useVoiceApp from './hooks/useVoiceApp';
import { useApp } from './context/AppContext';
import { unlockAudio } from './services/tts';
import './styles/components/VoiceScreen.css';

function AppContent({ onBack }) {
  const { state, toggleListening, resetTrip } = useVoiceApp();
  const phase = state.appState;
  const riding = phase === 'in_progress' || phase === 'completed';   // trip underway/done
  // Map is shown in these phases (driven by appState, NOT by whether data exists —
  // so re-asking collapses the map but keeps the destination/quote data).
  const mapActive = ['destination_set', 'confirming', 'trip_live', 'in_progress', 'completed'].includes(phase);

  return (
    <div className={`voice-screen ${mapActive ? 'map-active' : ''} ${riding ? 'riding' : ''}`}>
      <Header onBack={onBack} />
      <div className="voice-stage">
        {!riding && <AgentStage compact={mapActive} />}
        <div className="map-stage">
          <MapView />
          {!riding && <TripInfo />}
          {phase === 'in_progress' && <RideMoving />}
        </div>
      </div>
      {!riding && (
        <div className="voice-controls">
          <RecordButton recording={state.recording} onToggle={toggleListening} />
          <span className="voice-controls-hint">{state.recording ? 'Đang nghe… chạm để dừng' : 'Chạm để nói lại'}</span>
        </div>
      )}
      <TripOverlay onDismiss={resetTrip} />
      {phase === 'completed' && <RideArrived onHome={onBack} />}
    </div>
  );
}

function MainContainer() {
  const { state, dispatch } = useApp();

  const handleLogin = (userData) => dispatch({ type: 'SET_USER', payload: userData });
  const goVoice = (vehicle) => {
    unlockAudio();   // this tap unlocks mobile audio for later socket-triggered TTS
    if (vehicle) dispatch({ type: 'SET_VEHICLE_TYPE', payload: vehicle });
    dispatch({ type: 'SET_SCREEN', payload: 'voice' });
  };
  const goHome = () => { dispatch({ type: 'RESET_TRIP' }); dispatch({ type: 'SET_SCREEN', payload: 'home' }); };

  if (!state.user) return <LoginPage onLogin={handleLogin} />;
  if (state.user.role === 'driver') return <DriverView user={state.user} />;
  if (state.screen === 'home') return <HomeView user={state.user} onBook={goVoice} />;
  return <AppContent onBack={goHome} />;
}

export default function App() {
  return (
    <AppProvider>
      <MainContainer />
    </AppProvider>
  );
}
