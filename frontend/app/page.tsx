"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Menu, Trash2, Loader2, Download } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ChatSidebar, type SidebarView } from "@/components/chat-sidebar";
import { ChatMessageList } from "@/components/chat-message-list";
import { ChatInput } from "@/components/chat-input";
import { KnowledgeBase } from "@/components/knowledge-base";
import { useAuth } from "@/components/auth-provider";
import { useThreads } from "@/hooks/use-threads";
import { useChat } from "@/hooks/use-chat";
import { usePapers } from "@/hooks/use-papers";
import { downloadReport } from "@/lib/api";
import type { AgentMode } from "@/lib/types";

export default function Home() {
  const router = useRouter();
  const { user, isLoading, logout } = useAuth();

  useEffect(() => {
    if (!isLoading && !user) router.replace("/login");
  }, [user, isLoading, router]);

  if (isLoading || !user) {
    return (
      <div className="flex h-dvh w-full items-center justify-center">
        <Loader2 className="size-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <AppContent
      username={user.username}
      userId={user.user_id}
      onLogout={logout}
    />
  );
}

function AppContent({
  username,
  userId,
  onLogout,
}: {
  username: string;
  userId: string;
  onLogout: () => void;
}) {
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
    rewindCheckpointId,
    rewindDraft,
    sendMessage,
    resume,
    rewindTo,
    cancelRewind,
    stopStreaming,
  } = useChat(currentThreadId, refresh, userId);

  const {
    files,
    isLoading: isLoadingPapers,
    isUploading,
    error: paperError,
    upload,
    remove: removePaper,
  } = usePapers();

  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [view, setView] = useState<SidebarView>("chat");
  const [agentMode, setAgentMode] = useState<AgentMode>("single");
  const [downloading, setDownloading] = useState(false);

  useEffect(() => {
    if (!currentThreadId) return;
    const t = threads.find((it) => it.thread_id === currentThreadId);
    if (t?.agent_mode) setAgentMode(t.agent_mode);
  }, [currentThreadId, threads]);

  useEffect(() => {
    if (view === "chat" && !isLoadingThreads && !currentThreadId) {
      createNewThread();
    }
  }, [view, isLoadingThreads, currentThreadId, createNewThread]);

  const handleNewThread = () => {
    setView("chat");
    createNewThread();
    setSidebarOpen(false);
  };

  const handleSelectThread = (threadId: string) => {
    setView("chat");
    selectThread(threadId);
    setSidebarOpen(false);
  };

  const handleSelectView = (newView: SidebarView) => {
    setView(newView);
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

  const handleDownload = async () => {
    if (!currentThreadId || downloading) return;
    setDownloading(true);
    try {
      await downloadReport(currentThreadId);
    } catch (err) {
      console.error("[download] error:", err);
    } finally {
      setDownloading(false);
    }
  };

  const showDownload =
    agentMode === "multi" &&
    !isStreaming &&
    messages.length > 0;

  return (
    <div className="flex h-dvh w-full overflow-hidden">
      <ChatSidebar
        threads={threads}
        currentThreadId={currentThreadId}
        isLoading={isLoadingThreads}
        isOpen={sidebarOpen}
        view={view}
        username={username}
        onClose={() => setSidebarOpen(false)}
        onNewThread={handleNewThread}
        onSelectThread={handleSelectThread}
        onDeleteThread={handleDeleteThread}
        onSelectView={handleSelectView}
        onLogout={onLogout}
      />

      <main className="flex flex-1 flex-col overflow-hidden">
        {view === "knowledge" ? (
          <KnowledgeBase
            files={files}
            isLoading={isLoadingPapers}
            isUploading={isUploading}
            error={paperError}
            onUpload={upload}
            onDelete={removePaper}
          />
        ) : (
          <>
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
                <div className="flex items-center gap-1">
                  {showDownload && (
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      onClick={handleDownload}
                      disabled={downloading}
                      title="下载 Markdown 报告"
                    >
                      {downloading ? (
                        <Loader2 className="size-4 animate-spin" />
                      ) : (
                        <Download className="size-4" />
                      )}
                    </Button>
                  )}
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    onClick={handleDeleteCurrent}
                    title="删除当前对话"
                  >
                    <Trash2 className="text-destructive" />
                  </Button>
                </div>
              )}
            </header>

            {error && (
              <div className="border-b border-destructive/20 bg-destructive/5 px-4 py-2 text-sm text-destructive">
                {error}
              </div>
            )}

            {rewindCheckpointId && (
              <div className="flex items-center justify-between border-b border-primary/20 bg-primary/5 px-4 py-2 text-sm">
                <span className="text-primary">
                  已进入回溯模式，发送消息将从该点重新生成对话
                </span>
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-6 px-2 text-xs"
                  onClick={() => cancelRewind()}
                >
                  取消回溯
                </Button>
              </div>
            )}

            <ChatMessageList
              messages={messages}
              isLoadingHistory={isLoadingHistory}
              onDownload={handleDownload}
              onRewind={rewindTo}
              onResume={() => resume(agentMode)}
              canRewind={agentMode === "single" && !isStreaming && !rewindCheckpointId}
            />

            <ChatInput
              isStreaming={isStreaming}
              mode={agentMode}
              onModeChange={setAgentMode}
              onSend={(content) => sendMessage(content, agentMode)}
              onStop={stopStreaming}
              prefillValue={rewindDraft}
            />
          </>
        )}
      </main>
    </div>
  );
}
