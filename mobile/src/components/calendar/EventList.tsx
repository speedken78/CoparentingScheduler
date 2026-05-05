import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { CustodyEvent } from '../../api/types';
import { colors } from '../../theme/colors';
import { spacing, radius } from '../../theme/spacing';
import { typography } from '../../theme/typography';
import { formatEventTime } from '../../utils/formatDate';
import { Pill } from '../ui/Pill';

interface Props {
  events: CustodyEvent[];
  currentUserId: string;
}

export const EventList = ({ events, currentUserId }: Props) => {
  if (events.length === 0) {
    return <Text style={styles.empty}>這天沒有排程</Text>;
  }
  return (
    <View style={styles.container}>
      {events.map(e => {
        const isMe = e.custodian_id === currentUserId;
        return (
          <View key={e.id} style={styles.row}>
            <View style={[styles.stripe, isMe ? styles.stripeMe : styles.stripeOther]} />
            <View style={styles.content}>
              <Text style={styles.time}>
                {formatEventTime(e.starts_at)}–{formatEventTime(e.ends_at)}
              </Text>
              {e.notes && <Text style={styles.notes} numberOfLines={1}>{e.notes}</Text>}
            </View>
            <Pill type={isMe ? 'me' : 'other'} />
          </View>
        );
      })}
    </View>
  );
};

const styles = StyleSheet.create({
  container: { gap: spacing.xs },
  empty: { ...typography.caption, color: colors.text.tertiary, textAlign: 'center', marginTop: spacing.md },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: colors.background.card,
    borderRadius: radius.md,
    overflow: 'hidden',
    borderWidth: 0.5,
    borderColor: colors.border.light,
    gap: spacing.sm,
    paddingRight: spacing.sm,
    paddingVertical: spacing.sm,
  },
  stripe: { width: 3, alignSelf: 'stretch' },
  stripeMe: { backgroundColor: colors.brand.primary },
  stripeOther: { backgroundColor: colors.counterparty.primary },
  content: { flex: 1, paddingLeft: spacing.sm },
  time: { ...typography.body, color: colors.text.primary },
  notes: { ...typography.caption, color: colors.text.tertiary, marginTop: 2 },
});
