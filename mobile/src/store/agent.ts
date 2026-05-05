import { create } from 'zustand';

interface AgentState {
  sessionId: string | undefined;
  setSessionId: (id: string) => void;
  clearSession: () => void;
}

export const useAgentStore = create<AgentState>((set) => ({
  sessionId: undefined,
  setSessionId: (id) => set({ sessionId: id }),
  clearSession: () => set({ sessionId: undefined }),
}));
