import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { colors } from '../../theme/colors';
import { spacing, radius } from '../../theme/spacing';
import { typography } from '../../theme/typography';

interface Props {
  icon?: string;
  text: string;
}

export const AlertBanner = ({ icon = '⚑', text }: Props) => (
  <View style={styles.banner}>
    <Text style={styles.icon}>{icon}</Text>
    <Text style={styles.text}>{text}</Text>
  </View>
);

const styles = StyleSheet.create({
  banner: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: colors.conflict.background,
    borderWidth: 1,
    borderColor: colors.conflict.border,
    borderRadius: radius.md,
    padding: spacing.md,
    marginBottom: spacing.md,
    gap: spacing.sm,
  },
  icon: { fontSize: 14, color: colors.conflict.text },
  text: { ...typography.body, color: colors.conflict.text, flex: 1 },
});
