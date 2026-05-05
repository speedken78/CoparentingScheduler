import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { colors } from '../../theme/colors';
import { spacing, radius } from '../../theme/spacing';
import { typography } from '../../theme/typography';

interface Props {
  label: string;
  value: string;
  sub?: string;
  valueSize?: 'large' | 'small';
}

export const StatCard = ({ label, value, sub, valueSize = 'large' }: Props) => (
  <View style={styles.card}>
    <Text style={styles.label}>{label}</Text>
    <Text style={[styles.value, valueSize === 'small' && styles.valueSmall]}>{value}</Text>
    {sub && <Text style={styles.sub}>{sub}</Text>}
  </View>
);

const styles = StyleSheet.create({
  card: {
    flex: 1,
    backgroundColor: colors.background.secondary,
    borderRadius: radius.md,
    padding: spacing.md,
  },
  label: { ...typography.caption, color: colors.text.tertiary, marginBottom: 4 },
  value: { ...typography.h1, color: colors.text.primary, marginBottom: 2 },
  valueSmall: { fontSize: 16 },
  sub: { ...typography.caption, color: colors.text.secondary },
});
