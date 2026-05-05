import { apiClient } from './client';
import { User } from './types';

export const authApi = {
  async getMobileLoginUrl(): Promise<string> {
    const { data } = await apiClient.get<{ auth_url: string }>('/auth/google/login/mobile');
    return data.auth_url;
  },

  async me(): Promise<User> {
    const { data } = await apiClient.get<User>('/auth/me');
    return data;
  },

  async refresh(refreshToken: string): Promise<string> {
    const { data } = await apiClient.post<{ access_token: string }>('/auth/refresh', {
      refresh_token: refreshToken,
    });
    return data.access_token;
  },
};
