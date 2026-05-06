import React, { useState, useRef } from 'react';
import { View, Text, ScrollView, StyleSheet, KeyboardAvoidingView, Platform } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useCaseStore } from '../store/case';
import { agentApi } from '../api/agent';
import { MessageBubble } from '../components/chat/MessageBubble';
import { ClarifyOptions } from '../components/chat/ClarifyOptions';
import { DoneBox } from '../components/chat/DoneBox';
import { ChatInput } from '../components/chat/ChatInput';
import { colors } from '../theme/colors';
import { spacing } from '../theme/spacing';
import { typography } from '../theme/typography';

interface ChatMessage {
  id: string;
  role: 'user' | 'ai';
  text: string;
  options?: { label: string; interpretation_note?: string }[];
  doneBoxes?: { title: string; details: string[] }[];
  timestamp: string;
}

const WELCOME_MSG: ChatMessage = {
  id: '0',
  role: 'ai',
  text: '您好！請用自然語言描述監護安排，我會幫您自動建立行事曆與法律紀錄。',
  timestamp: new Date().toISOString(),
};

export const ChatScreen = () => {
  const insets = useSafeAreaInsets();
  const { currentCase } = useCaseStore();
  const [messages, setMessages] = useState<ChatMessage[]>([WELCOME_MSG]);
  const [sessionId, setSessionId] = useState<string | undefined>(undefined);
  const [isSending, setIsSending] = useState(false);
  const scrollRef = useRef<ScrollView>(null);

  const handleSend = async (text: string) => {
    if (!currentCase || !text.trim()) return;

    const userMsg: ChatMessage = {
      id: Date.now().toString(),
      role: 'user',
      text,
      timestamp: new Date().toISOString(),
    };
    setMessages(m => [...m, userMsg]);
    setIsSending(true);

    try {
      const response = await agentApi.sendMessage({
        case_id: currentCase.id,
        text,
        session_id: sessionId,
      });
      setSessionId(response.session_id);

      const aiMsg: ChatMessage = {
        id: response.session_id + '-' + Date.now(),
        role: 'ai',
        text: response.reply,
        timestamp: new Date().toISOString(),
      };

      if (response.requires_clarification && response.clarification_options.length > 0) {
        aiMsg.options = response.clarification_options;
      }

      const doneBoxes = response.actions_taken
        .filter(a => a.result?.status === 'created' || a.result?.status === 'success')
        .map(a => ({
          title: a.tool.includes('rule')
            ? '✓ 週期規則建立完成'
            : '✓ 事件建立完成',
          details: a.result.summary ? [String(a.result.summary)] : [],
        }));
      if (doneBoxes.length) aiMsg.doneBoxes = doneBoxes;

      setMessages(m => [...m, aiMsg]);
    } catch {
      setMessages(m => [...m, {
        id: 'err-' + Date.now(),
        role: 'ai',
        text: '抱歉，處理時發生錯誤，請稍後再試。',
        timestamp: new Date().toISOString(),
      }]);
    } finally {
      setIsSending(false);
      setTimeout(() => scrollRef.current?.scrollToEnd({ animated: true }), 100);
    }
  };

  return (
    <KeyboardAvoidingView
      style={styles.container}
      behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
    >
      <View style={[styles.header, { paddingTop: insets.top + spacing.md }]}>
        <Text style={styles.headerTitle}>AI 助理</Text>
        <Text style={styles.headerSub}>
          {currentCase ? currentCase.case_name : '請先建立案件'}
        </Text>
      </View>

      <ScrollView
        ref={scrollRef}
        style={styles.body}
        contentContainerStyle={styles.bodyContent}
        keyboardShouldPersistTaps="handled"
      >
        {messages.map(msg => (
          <View key={msg.id} style={styles.msgGroup}>
            <MessageBubble role={msg.role} text={msg.text} timestamp={msg.timestamp} />
            {msg.options && (
              <ClarifyOptions options={msg.options} onSelect={handleSend} />
            )}
            {msg.doneBoxes?.map((db, i) => (
              <DoneBox key={i} title={db.title} details={db.details} />
            ))}
          </View>
        ))}
      </ScrollView>

      <ChatInput onSend={handleSend} disabled={isSending || !currentCase} />
    </KeyboardAvoidingView>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.background.primary },
  header: {
    backgroundColor: colors.brand.primary,
    paddingHorizontal: spacing.lg,
    paddingBottom: spacing.lg,
  },
  headerTitle: { ...typography.h2, color: colors.text.inverse },
  headerSub: { ...typography.caption, color: colors.text.inverse, opacity: 0.8, marginTop: 2 },
  body: { flex: 1 },
  bodyContent: { padding: spacing.md },
  msgGroup: { marginBottom: spacing.sm },
});
