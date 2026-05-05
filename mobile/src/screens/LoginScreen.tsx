import React from 'react';
import { View, Text, StyleSheet, Alert } from 'react-native';
import * as WebBrowser from 'expo-web-browser';
import { Button } from '../components/ui/Button';
import { apiClient } from '../api/client';
import { useAuthStore } from '../store/auth';
import { colors } from '../theme/colors';
import { spacing } from '../theme/spacing';
import { typography } from '../theme/typography';
import { AUTH_REDIRECT_URI } from '../utils/constants';

WebBrowser.maybeCompleteAuthSession();

export const LoginScreen = () => {
  const { login } = useAuthStore();
  const [loading, setLoading] = React.useState(false);

  const handleGoogleSignIn = async () => {
    setLoading(true);
    try {
      const { data } = await apiClient.get<{ auth_url: string }>('/auth/google/login/mobile');

      const result = await WebBrowser.openAuthSessionAsync(data.auth_url, AUTH_REDIRECT_URI);

      if (result.type !== 'success') {
        return;
      }

      const url = new URL(result.url);
      const accessToken = url.searchParams.get('access_token');
      const refreshToken = url.searchParams.get('refresh_token');
      const userJson = url.searchParams.get('user');

      if (!accessToken || !refreshToken || !userJson) {
        throw new Error('Auth callback 缺少必要參數');
      }

      const user = JSON.parse(decodeURIComponent(userJson));
      await login(accessToken, refreshToken, user);
    } catch (e: any) {
      Alert.alert('登入失敗', e.message || '請稍後再試');
    } finally {
      setLoading(false);
    }
  };

  return (
    <View style={styles.container}>
      <View style={styles.brandSection}>
        <Text style={styles.logo}>⚖</Text>
        <Text style={styles.title}>共親職排程</Text>
        <Text style={styles.subtitle}>讓共同監護更有條理</Text>
      </View>

      <View style={styles.actionSection}>
        <Button onPress={handleGoogleSignIn} variant="primary" loading={loading}>
          使用 Google 帳號登入
        </Button>
        <Text style={styles.hint}>
          首次登入會請您授權 Google Calendar，讓排程自動同步
        </Text>
      </View>

      <Text style={styles.disclaimer}>
        本應用程式不提供法律意見。若需法律諮詢，請洽家事律師。
      </Text>
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.background.primary,
    padding: spacing.xl,
    justifyContent: 'space-between',
  },
  brandSection: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
  logo: { fontSize: 64, marginBottom: spacing.lg },
  title: { ...typography.h1, color: colors.text.primary, marginBottom: spacing.xs },
  subtitle: { ...typography.body, color: colors.text.secondary },
  actionSection: { marginBottom: spacing.xl },
  hint: {
    ...typography.caption,
    color: colors.text.tertiary,
    textAlign: 'center',
    marginTop: spacing.md,
  },
  disclaimer: {
    ...typography.caption,
    color: colors.text.tertiary,
    textAlign: 'center',
    marginBottom: spacing.lg,
  },
});
