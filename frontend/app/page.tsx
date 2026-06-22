"use client";

import { useEffect, useState } from "react";
import { Menu, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ChatSidebar } from "@/components/chat-sidebar";
import { ChatMessageList } from "@/components/chat-message-list";
import { ChatInput } from "@/components/chat-input";
import { useThreads } from "@/hooks/use-threads";
import { useChat } from "@/hooks/use-chat";

export default function Home() {
  const {
    threads,
    currentThreadId,
    isLoading: isLoadingThreads,
    refresh,
    createNewThread,
    selectThread,
    removeThread,
  } = useThreads();

  const {
    messages,
    isStreaming,
    isLoadingHistory,
    error,
    sendMessage,
    stopStreaming,
  } = useChat(currentThreadId, refresh);

  const [sidebarOpen, setSidebarOpen] = useState(false);

  useEffect(() => {
    if (!isLoadingThreads && !currentThreadId) {
      createNewThread();
    }
  }, [isLoadingThreads, currentThreadId, createNewThread]);

  const handleNewThread = () => {
    createNewThread();
    setSidebarOpen(false);
  };

  const handleSelectThread = (threadId: string) => {
    selectThread(threadId);
    setSidebarOpen(false);
  };

  const handleDeleteThread = (threadId: string) => {
    removeThread(threadId);
  };

  const handleDeleteCurrent = () => {
    if (currentThreadId) {
      removeThread(currentThreadId);
    }
  };

  const currentThread = threads.find((t) => t.thread_id === currentThreadId);
  const headerTitle = currentThread?.latest_message || "新对话";

  return (
    <div className="flex h-dvh w-full overflow-hidden">
      <ChatSidebar
        threads={threads}
        currentThreadId={currentThreadId}
        isLoading={isLoadingThreads}
        isOpen={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
        onNewThread={handleNewThread}
        onSelectThread={handleSelectThread}
        onDeleteThread={handleDeleteThread}
      />

      <main className="flex flex-1 flex-col overflow-hidden">
        <header className="flex items-center justify-between gap-2 border-b px-4 py-3">
          <div className="flex items-center gap-2">
            <Button
              variant="ghost"
              size="icon"
              className="md:hidden"
              onClick={() => setSidebarOpen(true)}
            >
              <Menu />
            </Button>
            <h1 className="truncate text-sm font-medium">{headerTitle}</h1>
          </div>
          {currentThreadId && (
            <Button
              variant="ghost"
              size="icon-sm"
              onClick={handleDeleteCurrent}
              title="删除当前对话"
            >
              <Trash2 className="text-destructive" />
            </Button>
          )}
        </header>

        {error && (
          <div className="border-b border-destructive/20 bg-destructive/5 px-4 py-2 text-sm text-destructive">
            {error}
          </div>
        )}

        <ChatMessageList
          messages={messages}
          isLoadingHistory={isLoadingHistory}
        />

        <ChatInput
          isStreaming={isStreaming}
          onSend={sendMessage}
          onStop={stopStreaming}
        />
      </main>
    </div>
  );
}
