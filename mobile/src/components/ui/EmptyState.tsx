import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { colors } from '../../theme/colors';
import { spacing } from '../../theme/spacing';
import { typography } from '../../theme/typography';

interface Props {
  icon?: string;
  title: string;
  subtitle?: string;
}

export const EmptyState = ({ icon = '📭', title, subtitle }: Props) => (
  <View style={styles.container}>
    <Text style={styles.icon}>{icon}</Text>
    <Text style={styles.title}>{title}</Text>
    {subtitle && <Text style={styles.subtitle}>{subtitle}</Text>}
  </View>
);

const styles = StyleSheet.create({
  container: { alignItems: 'center', padding: spacing.xxl },
  icon: { fontSize: 40, marginBottom: spacing.md },
  title: { ...typography.h3, color: colors.text.secondary, textAlign: 'center' },
  subtitle: { ...typography.body, color: colors.text.tertiary, textAlign: 'center', marginTop: spacing.xs },
});
