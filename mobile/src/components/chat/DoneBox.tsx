import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { colors } from '../../theme/colors';
import { spacing, radius } from '../../theme/spacing';
import { typography } from '../../theme/typography';

interface Props {
  title: string;
  details?: string[];
}

export const DoneBox = ({ title, details }: Props) => (
  <View style={styles.box}>
    <Text style={styles.title}>{title}</Text>
    {details?.map((d, i) => (
      <Text key={i} style={styles.detail}>{d}</Text>
    ))}
  </View>
);

const styles = StyleSheet.create({
  box: {
    marginTop: spacing.sm,
    backgroundColor: colors.status.successBackground,
    borderWidth: 1,
    borderColor: colors.status.successBorder,
    borderRadius: radius.md,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  title: { ...typography.bodyMedium, color: colors.status.successText },
  detail: { ...typography.caption, color: colors.status.successText, marginTop: 2 },
});
