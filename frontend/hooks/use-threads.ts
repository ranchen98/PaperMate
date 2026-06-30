"use client";

import { useCallback, useEffect, useState } from "react";
import { deleteThread, fetchThreads } from "@/lib/api";
import { generateThreadId, type Thread } from "@/lib/types";

export function useThreads(enabled: boolean = true) {
  const [threads, setThreads] = useState<Thread[]>([]);
  const [currentThreadId, setCurrentThreadId] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const list = await fetchThreads();
      setThreads(list);
      return list;
    } catch (err) {
      console.error("[useThreads] refresh error:", err);
      return [];
    }
  }, []);

  const loadInitial = useCallback(async () => {
    setIsLoading(true);
    const list = await refresh();
    if (list.length > 0) {
      setCurrentThreadId(list[0].thread_id);
    }
    setIsLoading(false);
  }, [refresh]);

  useEffect(() => {
    if (!enabled) {
      setIsLoading(false);
      return;
    }
    loadInitial();
  }, [enabled, loadInitial]);

  const createNewThread = useCallback(() => {
    const id = generateThreadId();
    setCurrentThreadId(id);
    return id;
  }, []);

  const selectThread = useCallback((threadId: string) => {
    setCurrentThreadId(threadId);
  }, []);

  const removeThread = useCallback(
    async (threadId: string) => {
      try {
        await deleteThread(threadId);
      } catch (err) {
        console.error("[useThreads] delete error:", err);
      }
      const updated = threads.filter((t) => t.thread_id !== threadId);
      setThreads(updated);
      if (currentThreadId === threadId) {
        setCurrentThreadId(updated[0]?.thread_id ?? null);
      }
    },
    [threads, currentThreadId],
  );

  return {
    threads,
    currentThreadId,
    isLoading,
    refresh,
    createNewThread,
    selectThread,
    removeThread,
  };
}
