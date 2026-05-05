import { create } from 'zustand';
import { Case } from '../api/types';

interface CaseState {
  currentCase: Case | null;
  cases: Case[];
  setCurrentCase: (c: Case) => void;
  setCases: (cs: Case[]) => void;
}

export const useCaseStore = create<CaseState>((set) => ({
  currentCase: null,
  cases: [],
  setCurrentCase: (c) => set({ currentCase: c }),
  setCases: (cs) => set({ cases: cs }),
}));
