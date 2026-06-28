import React, { createContext, useContext, useReducer } from 'react';

const AppContext = createContext(null);

// State shape
const initialState = {
  appState: 'idle', // idle | listening | destination_set | confirming | booking | trip_live
  screen: 'home',      // 'home' (Grab-like landing) | 'voice' (booking agent)
  user: null,          // { id, role, ... }
  backendOnline: false,
  origin: { name: 'Trường Đại học Quốc tế', lat: 10.8782, lng: 106.8012 },
  destination: null,   // { name, address, lat, lng, accessible? }
  candidates: null,    // [{ name, address, lat, lng, accessible? }] shown on the map
  vehicleType: 'bike', // bike | car
  quote: null,         // { price, distance, duration, geometry }
  booking: null,       // { id, driver, vehicle, ... }
  driver: null,        // { name, phone, plate, rating }
  pin: null,           // string, 4-digit PIN
  messages: [],        // conversation history for agent
  transcript: '',      // live speech transcript
  status: 'Đang khởi động…',
  substatus: '',
  recording: false,
  busy: false,
  agentLog: [],        // array of log lines for agent overlay
  agentResult: '',     // final agent result text
  agentStream: '',     // agent reply streamed word-by-word (shown on the stage)
};

function appReducer(state, action) {
  switch (action.type) {
    case 'SET_STATE': return { ...state, appState: action.payload };
    case 'SET_SCREEN': return { ...state, screen: action.payload };
    case 'SET_USER': return { ...state, user: action.payload };
    case 'SET_BACKEND_ONLINE': return { ...state, backendOnline: action.payload };
    case 'SET_DESTINATION': return { ...state, destination: action.payload };
    case 'SET_CANDIDATES': return { ...state, candidates: action.payload };
    case 'SET_VEHICLE_TYPE': return { ...state, vehicleType: action.payload };
    case 'SET_QUOTE': return { ...state, quote: action.payload };
    case 'SET_BOOKING': return { ...state, booking: action.payload };
    case 'SET_DRIVER': return { ...state, driver: action.payload };
    case 'SET_PIN': return { ...state, pin: action.payload };
    case 'SET_MESSAGES': return { ...state, messages: action.payload };
    case 'ADD_MESSAGE': return { ...state, messages: [...state.messages, action.payload] };
    case 'SET_TRANSCRIPT': return { ...state, transcript: action.payload };
    case 'SET_STATUS': return { ...state, status: action.payload.main, substatus: action.payload.sub || '' };
    case 'SET_RECORDING': return { ...state, recording: action.payload };
    case 'SET_BUSY': return { ...state, busy: action.payload };
    case 'SET_AGENT_LOG': return { ...state, agentLog: action.payload };
    case 'ADD_AGENT_LOG': return { ...state, agentLog: [...state.agentLog, action.payload] };
    case 'SET_AGENT_RESULT': return { ...state, agentResult: action.payload };
    case 'SET_STREAM': return { ...state, agentStream: action.payload };
    case 'RESET_TRIP': return {
      ...state,
      appState: 'idle',
      destination: null,
      candidates: null,
      quote: null,
      booking: null,
      driver: null,
      pin: null,
      messages: [],
      transcript: '',
      agentLog: [],
      agentResult: '',
      agentStream: '',
      status: 'Chạm mic và nói điểm đến',
      substatus: '',
      busy: false,
      recording: false,
    };
    default: return state;
  }
}

export function AppProvider({ children }) {
  const [state, dispatch] = useReducer(appReducer, initialState);
  return (
    <AppContext.Provider value={{ state, dispatch }}>
      {children}
    </AppContext.Provider>
  );
}

export function useApp() {
  const ctx = useContext(AppContext);
  if (!ctx) throw new Error('useApp must be used within AppProvider');
  return ctx;
}

export default AppContext;
