import React from 'react';
import { TouchableOpacity, Text, StyleSheet, ActivityIndicator } from 'react-native';
import { colors } from '../../theme/colors';
import { spacing, radius } from '../../theme/spacing';
import { typography } from '../../theme/typography';

interface Props {
  onPress: () => void;
  variant?: 'primary' | 'secondary';
  disabled?: boolean;
  loading?: boolean;
  children: string;
}

export const Button = ({ onPress, variant = 'primary', disabled, loading, children }: Props) => (
  <TouchableOpacity
    onPress={onPress}
    disabled={disabled || loading}
    style={[
      styles.base,
      variant === 'primary' ? styles.primary : styles.secondary,
      (disabled || loading) && styles.disabled,
    ]}
    activeOpacity={0.8}
  >
    {loading ? (
      <ActivityIndicator color={variant === 'primary' ? colors.text.inverse : colors.brand.primary} />
    ) : (
      <Text style={[styles.text, variant === 'primary' ? styles.textPrimary : styles.textSecondary]}>
        {children}
      </Text>
    )}
  </TouchableOpacity>
);

const styles = StyleSheet.create({
  base: {
    paddingHorizontal: spacing.xl,
    paddingVertical: spacing.md,
    borderRadius: radius.pill,
    alignItems: 'center',
    justifyContent: 'center',
    minHeight: 44,
  },
  primary: { backgroundColor: colors.brand.primary },
  secondary: {
    backgroundColor: 'transparent',
    borderWidth: 1,
    borderColor: colors.brand.primary,
  },
  disabled: { opacity: 0.5 },
  text: { ...typography.bodyMedium },
  textPrimary: { color: colors.text.inverse },
  textSecondary: { color: colors.brand.primary },
});
