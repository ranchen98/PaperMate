"use client";

import { Plus, MessageSquare, Trash2, X, Library, LogOut, User } from "lucide-react";
import { cn, formatTime } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { ModeToggle } from "@/components/mode-toggle";
import type { Thread } from "@/lib/types";

export type SidebarView = "chat" | "knowledge";

type ChatSidebarProps = {
  threads: Thread[];
  currentThreadId: string | null;
  isLoading: boolean;
  isOpen: boolean;
  view: SidebarView;
  username: string;
  onClose: () => void;
  onNewThread: () => void;
  onSelectThread: (threadId: string) => void;
  onDeleteThread: (threadId: string) => void;
  onSelectView: (view: SidebarView) => void;
  onLogout: () => void;
};

export function ChatSidebar({
  threads,
  currentThreadId,
  isLoading,
  isOpen,
  view,
  username,
  onClose,
  onNewThread,
  onSelectThread,
  onDeleteThread,
  onSelectView,
  onLogout,
}: ChatSidebarProps) {
  return (
    <>
      {isOpen && (
        <div
          className="fixed inset-0 z-30 bg-black/40 md:hidden"
          onClick={onClose}
        />
      )}

      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-40 flex w-72 flex-col border-r bg-sidebar transition-transform md:static md:translate-x-0",
          isOpen ? "translate-x-0" : "-translate-x-full",
        )}
      >
        <div className="flex items-center justify-between gap-2 border-b px-4 py-3">
          <div className="flex items-center gap-2">
            <MessageSquare className="size-5 text-primary" />
            <span className="text-lg font-semibold">PaperMate</span>
          </div>
          <div className="flex items-center gap-1">
            <ModeToggle />
            <Button
              variant="ghost"
              size="icon"
              className="md:hidden"
              onClick={onClose}
            >
              <X />
            </Button>
          </div>
        </div>

        <div className="px-3 pb-2">
          <div
            className={cn(
              "group flex cursor-pointer items-center gap-2 rounded-lg px-3 py-2.5 transition-colors",
              view === "knowledge"
                ? "bg-sidebar-accent text-sidebar-accent-foreground"
                : "hover:bg-sidebar-accent/60",
            )}
            onClick={() => onSelectView("knowledge")}
          >
            <Library
              className={cn(
                "size-4 shrink-0",
                view === "knowledge"
                  ? "text-sidebar-accent-foreground"
                  : "text-muted-foreground",
              )}
            />
            <span className="text-sm font-medium">知识库</span>
          </div>
        </div>

        <div className="border-t px-3 py-2">
          <span className="px-3 text-xs font-medium text-muted-foreground">
            对话列表
          </span>
        </div>

        <div className="flex-1 overflow-y-auto px-2 pb-3">
          <div className="sticky top-0 z-10 bg-sidebar py-1">
            <div
              className="flex cursor-pointer items-center gap-2 rounded-lg px-3 py-2.5 transition-colors hover:bg-sidebar-accent/60"
              onClick={onNewThread}
            >
              <Plus className="size-4 shrink-0 text-primary" />
              <span className="text-sm font-medium">新建对话</span>
            </div>
          </div>
          {isLoading ? (
            <div className="space-y-2 px-2 py-2">
              {[1, 2, 3].map((i) => (
                <div
                  key={i}
                  className="h-14 animate-pulse rounded-lg bg-muted"
                />
              ))}
            </div>
          ) : threads.length === 0 ? (
            <p className="px-3 py-8 text-center text-sm text-muted-foreground">
              暂无会话
            </p>
          ) : (
            <ul className="space-y-1">
              {threads.map((thread) => {
                const active = thread.thread_id === currentThreadId;
                return (
                  <li key={thread.thread_id}>
                    <div
                      className={cn(
                        "group flex cursor-pointer items-center gap-2 rounded-lg px-3 py-2.5 transition-colors",
                        active
                          ? "bg-sidebar-accent text-sidebar-accent-foreground"
                          : "hover:bg-sidebar-accent/60",
                      )}
                      onClick={() => onSelectThread(thread.thread_id)}
                    >
                      <MessageSquare
                        className={cn(
                          "size-4 shrink-0",
                          active
                            ? "text-sidebar-accent-foreground"
                            : "text-muted-foreground",
                        )}
                      />
                      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                        <span className="truncate text-sm font-medium">
                          {thread.latest_message || "新对话"}
                        </span>
                        <span className="text-xs text-muted-foreground">
                          {formatTime(thread.update_time)}
                        </span>
                      </div>
                      <Button
                        variant="ghost"
                        size="icon-xs"
                        className="shrink-0 opacity-0 transition-opacity group-hover:opacity-100"
                        onClick={(e) => {
                          e.stopPropagation();
                          onDeleteThread(thread.thread_id);
                        }}
                        title="删除对话"
                      >
                        <Trash2 className="text-destructive" />
                      </Button>
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        <div className="border-t px-3 py-2">
          <div className="flex items-center gap-2 rounded-lg px-3 py-2">
            <User className="size-4 shrink-0 text-muted-foreground" />
            <span className="min-w-0 flex-1 truncate text-sm font-medium">
              {username}
            </span>
            <Button
              variant="ghost"
              size="icon-xs"
              className="shrink-0"
              onClick={onLogout}
              title="退出登录"
            >
              <LogOut className="text-muted-foreground" />
            </Button>
          </div>
        </div>
      </aside>
    </>
  );
}
