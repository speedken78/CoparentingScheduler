import { create } from 'zustand';
import { User } from '../api/types';
import { secureStorage } from '../utils/secureStorage';
import { apiClient } from '../api/client';

interface AuthState {
  user: User | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  login: (accessToken: string, refreshToken: string, user: User) => Promise<void>;
  logout: () => Promise<void>;
  loadFromStorage: () => Promise<void>;
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  isAuthenticated: false,
  isLoading: true,

  login: async (accessToken, refreshToken, user) => {
    await secureStorage.setAccessToken(accessToken);
    await secureStorage.setRefreshToken(refreshToken);
    set({ user, isAuthenticated: true, isLoading: false });
  },

  logout: async () => {
    await secureStorage.clearTokens();
    set({ user: null, isAuthenticated: false });
  },

  loadFromStorage: async () => {
    const token = await secureStorage.getAccessToken();
    if (!token) {
      set({ isLoading: false });
      return;
    }
    try {
      const { data } = await apiClient.get<User>('/auth/me');
      set({ user: data, isAuthenticated: true, isLoading: false });
    } catch {
      await secureStorage.clearTokens();
      set({ isLoading: false });
    }
  },
}));
