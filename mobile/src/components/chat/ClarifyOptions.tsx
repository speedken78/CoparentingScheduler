import React from 'react';
import { View, Text, TouchableOpacity, StyleSheet } from 'react-native';
import { colors } from '../../theme/colors';
import { spacing, radius } from '../../theme/spacing';
import { typography } from '../../theme/typography';

interface Option {
  label: string;
  interpretation_note?: string;
}

interface Props {
  options: Option[];
  onSelect: (label: string) => void;
}

export const ClarifyOptions = ({ options, onSelect }: Props) => (
  <View style={styles.container}>
    {options.map((opt, i) => (
      <TouchableOpacity
        key={i}
        style={styles.option}
        onPress={() => onSelect(opt.label)}
        activeOpacity={0.7}
      >
        <Text style={styles.label}>{opt.label}</Text>
        {opt.interpretation_note && (
          <Text style={styles.note}>{opt.interpretation_note}</Text>
        )}
      </TouchableOpacity>
    ))}
  </View>
);

const styles = StyleSheet.create({
  container: {
    marginTop: spacing.sm,
    gap: spacing.xs,
  },
  option: {
    borderWidth: 1,
    borderColor: colors.brand.primary,
    borderRadius: radius.md,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    backgroundColor: colors.background.primary,
  },
  label: { ...typography.bodyMedium, color: colors.brand.primaryAccent },
  note: { ...typography.caption, color: colors.text.tertiary, marginTop: 2 },
});
