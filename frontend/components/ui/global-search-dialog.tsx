"use client"

import React, { useState, useEffect, useRef, useCallback } from "react"
import { motion, AnimatePresence } from "framer-motion"
import {
  Search,
  X,
  Clock,
  User,
  Users,
  FileText,
  Image as ImageIcon,
  MessageSquare,
  ChevronRight,
  Filter,
} from "lucide-react"
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar"
import { Badge } from "@/components/ui/badge"
import { Loader } from "@/components/ui/loader"
import { call } from "@/src/native"
import { cn } from "@/lib/utils"

interface SearchResultItem {
  session: string
  session_name: string
  session_avatar: string
  is_group: boolean
  msg_id: string
  local_id: number
  server_id: string
  create_time: number
  time_str: string
  sender: string
  sender_wxid: string
  avatar_url: string
  is_sender: boolean
  kind: string
  text: string
  snippet: string
  extra: any
}

interface SessionGroup {
  session: string
  display: string
  avatar_url: string
  is_group: boolean
  count: number
}

interface GlobalSearchDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  onSelectResult: (sessionId: string, msgId?: string) => void
  initialQuery?: string
}

function HighlightedText({ text, query }: { text: string; query: string }) {
  if (!query.trim() || !text) return <span>{text}</span>
  const q = query.trim().toLowerCase()
  const lower = text.toLowerCase()
  const parts: React.ReactNode[] = []
  let lastIdx = 0

  while (true) {
    const idx = lower.indexOf(q, lastIdx)
    if (idx === -1) {
      parts.push(text.slice(lastIdx))
      break
    }
    if (idx > lastIdx) {
      parts.push(text.slice(lastIdx, idx))
    }
    parts.push(
      <mark
        key={idx}
        className="bg-primary/25 text-primary dark:text-primary-foreground font-semibold px-0.5 rounded"
      >
        {text.slice(idx, idx + q.length)}
      </mark>
    )
    lastIdx = idx + q.length
  }

  return <span>{parts}</span>
}

export function GlobalSearchDialog({
  open,
  onOpenChange,
  onSelectResult,
  initialQuery = "",
}: GlobalSearchDialogProps) {
  const [query, setQuery] = useState(initialQuery)
  const [kind, setKind] = useState("all")
  const [selectedSession, setSelectedSession] = useState<string | null>(null)
  const [results, setResults] = useState<SearchResultItem[]>([])
  const [sessionGroups, setSessionGroups] = useState<SessionGroup[]>([])
  const [total, setTotal] = useState(0)
  const [sessionsHit, setSessionsHit] = useState(0)
  const [loading, setLoading] = useState(false)
  const [selectedIndex, setSelectedIndex] = useState(0)

  const inputRef = useRef<HTMLInputElement>(null)
  const searchTimeoutRef = useRef<any>(null)
  const resultsContainerRef = useRef<HTMLDivElement>(null)

  const executeSearch = useCallback(
    async (q: string, targetKind: string, targetSession: string | null) => {
      const trimmed = q.trim()
      if (!trimmed && targetKind === "all") {
        setResults([])
        setSessionGroups([])
        setTotal(0)
        setSessionsHit(0)
        setLoading(false)
        return
      }

      setLoading(true)
      try {
        const res = await call("global_search", {
          query: trimmed,
          kind: targetKind,
          session: targetSession || undefined,
          limit: 100,
        })
        setResults(res.items || [])
        if (!targetSession) {
          setSessionGroups(res.session_groups || [])
          setSessionsHit(res.sessions_hit || 0)
        }
        setTotal(res.total || 0)
        setSelectedIndex(0)
      } catch (err) {
        console.error("Global search error:", err)
      } finally {
        setLoading(false)
      }
    },
    []
  )

  // Debounced search on query/kind/session change
  useEffect(() => {
    if (!open) return
    clearTimeout(searchTimeoutRef.current)
    searchTimeoutRef.current = setTimeout(() => {
      executeSearch(query, kind, selectedSession)
    }, 200)
    return () => clearTimeout(searchTimeoutRef.current)
  }, [open, query, kind, selectedSession, executeSearch])

  // Reset and focus when opening
  useEffect(() => {
    if (open) {
      if (initialQuery && initialQuery !== query) {
        setQuery(initialQuery)
      }
      setSelectedSession(null)
      setTimeout(() => inputRef.current?.focus(), 50)
    }
  }, [open, initialQuery])

  // Keyboard navigation inside search results
  useEffect(() => {
    if (!open) return
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault()
        onOpenChange(false)
      } else if (e.key === "ArrowDown") {
        e.preventDefault()
        setSelectedIndex((prev) => Math.min(prev + 1, results.length - 1))
      } else if (e.key === "ArrowUp") {
        e.preventDefault()
        setSelectedIndex((prev) => Math.max(prev - 1, 0))
      } else if (e.key === "Enter" && results.length > 0) {
        e.preventDefault()
        const target = results[selectedIndex]
        if (target) {
          onSelectResult(target.session, target.msg_id)
          onOpenChange(false)
        }
      }
    }
    window.addEventListener("keydown", handleKeyDown)
    return () => window.removeEventListener("keydown", handleKeyDown)
  }, [open, results, selectedIndex, onOpenChange, onSelectResult])

  if (!open) return null

  return (
    <AnimatePresence>
      <div className="fixed inset-0 z-[160] flex items-start justify-center pt-16 px-4">
        {/* Backdrop */}
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.15 }}
          className="fixed inset-0 bg-background/80 backdrop-blur-sm"
          onClick={() => onOpenChange(false)}
        />

        {/* Modal Container */}
        <motion.div
          initial={{ opacity: 0, scale: 0.96, y: -10 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          exit={{ opacity: 0, scale: 0.96, y: -10 }}
          transition={{ duration: 0.2, ease: [0.16, 1, 0.3, 1] }}
          className="relative w-full max-w-3xl bg-card rounded-2xl shadow-2xl border border-border/40 overflow-hidden flex flex-col max-h-[80vh] z-10"
        >
          {/* Top Search Input Bar */}
          <div className="flex items-center px-4 py-3.5 border-b border-border/40 gap-3">
            <Search className="w-5 h-5 text-muted-foreground/70 shrink-0" />
            <input
              ref={inputRef}
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="跨全部会话搜索聊天记录、文件或图片内容..."
              className="flex-1 bg-transparent text-base outline-none text-foreground placeholder:text-muted-foreground/50"
            />
            {query && (
              <button
                type="button"
                onClick={() => setQuery("")}
                className="p-1 rounded-full text-muted-foreground/60 hover:text-foreground hover:bg-muted/60 transition-colors"
                title="清除"
              >
                <X className="w-4 h-4" />
              </button>
            )}
            <kbd className="hidden sm:inline-flex items-center gap-1 text-[11px] font-mono bg-muted/60 text-muted-foreground px-2 py-0.5 rounded border border-border/40">
              ESC
            </kbd>
          </div>

          {/* Sub Filters: Type Tabs & Hit Sessions */}
          <div className="px-4 py-2.5 bg-muted/20 border-b border-border/30 flex flex-wrap items-center justify-between gap-2 text-xs">
            {/* Kind Filter Pills */}
            <div className="flex items-center gap-1 bg-black/[0.04] dark:bg-white/[0.06] p-0.5 rounded-lg">
              {[
                { id: "all", label: "全部消息" },
                { id: "text", label: "文本" },
                { id: "media", label: "图片与视频" },
                { id: "file", label: "文件" },
              ].map((t) => (
                <button
                  key={t.id}
                  type="button"
                  onClick={() => setKind(t.id)}
                  className={cn(
                    "px-2.5 py-1 rounded-md font-medium transition-colors",
                    kind === t.id
                      ? "bg-card text-foreground shadow-sm"
                      : "text-muted-foreground hover:text-foreground"
                  )}
                >
                  {t.label}
                </button>
              ))}
            </div>

            {/* Total Hits Indicator */}
            {total > 0 && (
              <div className="text-muted-foreground">
                找到 <span className="font-semibold text-foreground">{total}</span> 条匹配
                {sessionsHit > 1 && (
                  <span>
                    ，涉及 <span className="font-semibold text-foreground">{sessionsHit}</span> 个会话
                  </span>
                )}
              </div>
            )}
          </div>

          {/* Session Breakdown Filter Pills (if results span multiple sessions) */}
          {sessionGroups.length > 1 && (
            <div className="px-4 py-2 border-b border-border/30 bg-muted/10 flex items-center gap-1.5 overflow-x-auto text-xs no-scrollbar">
              <span className="text-muted-foreground/70 shrink-0 mr-1 flex items-center gap-1">
                <Filter className="w-3 h-3" /> 会话:
              </span>
              <button
                type="button"
                onClick={() => setSelectedSession(null)}
                className={cn(
                  "px-2.5 py-0.5 rounded-full shrink-0 transition-colors",
                  selectedSession === null
                    ? "bg-primary text-primary-foreground font-medium"
                    : "bg-muted/60 text-muted-foreground hover:text-foreground"
                )}
              >
                全部 ({total})
              </button>
              {sessionGroups.map((sg) => (
                <button
                  key={sg.session}
                  type="button"
                  onClick={() =>
                    setSelectedSession(selectedSession === sg.session ? null : sg.session)
                  }
                  className={cn(
                    "px-2.5 py-0.5 rounded-full shrink-0 flex items-center gap-1.5 transition-colors",
                    selectedSession === sg.session
                      ? "bg-primary text-primary-foreground font-medium"
                      : "bg-muted/60 text-muted-foreground hover:text-foreground"
                  )}
                >
                  <span className="truncate max-w-[100px]">{sg.display}</span>
                  <span className="opacity-70">({sg.count})</span>
                </button>
              ))}
            </div>
          )}

          {/* Results List */}
          <div
            ref={resultsContainerRef}
            className="flex-1 overflow-y-auto min-h-[220px] max-h-[55vh] divide-y divide-border/20 p-2"
          >
            {loading && (
              <div className="flex flex-col items-center justify-center py-16 text-muted-foreground">
                <Loader size={20} className="mb-2 text-primary" />
                <span className="text-xs">正在跨会话高速检索...</span>
              </div>
            )}

            {!loading && !query.trim() && kind === "all" && (
              <div className="flex flex-col items-center justify-center py-16 text-center text-muted-foreground">
                <MessageSquare className="w-10 h-10 mb-3 opacity-25" />
                <p className="text-sm font-medium text-foreground/80 mb-1">全局聊天记录搜索</p>
                <p className="text-xs text-muted-foreground max-w-sm leading-relaxed">
                  键入关键字，即时穿透全部个人微信好友与群聊的历史消息，命中关键词可一键直达会话上下文。
                </p>
              </div>
            )}

            {!loading && (query.trim() || kind !== "all") && results.length === 0 && (
              <div className="flex flex-col items-center justify-center py-16 text-center text-muted-foreground">
                <Search className="w-10 h-10 mb-3 opacity-20" />
                <p className="text-sm font-medium text-foreground/80 mb-1">未找到匹配消息</p>
                <p className="text-xs text-muted-foreground">
                  尝试更换关键词、检查拼写或切换分类类型
                </p>
              </div>
            )}

            {!loading &&
              results.map((item, idx) => {
                const isSelected = idx === selectedIndex
                return (
                  <div
                    key={`${item.msg_id}-${idx}`}
                    onClick={() => {
                      onSelectResult(item.session, item.msg_id)
                      onOpenChange(false)
                    }}
                    onMouseEnter={() => setSelectedIndex(idx)}
                    className={cn(
                      "px-3.5 py-3 rounded-xl cursor-pointer transition-colors flex items-start gap-3",
                      isSelected
                        ? "bg-primary/10 dark:bg-primary/15"
                        : "hover:bg-muted/40"
                    )}
                  >
                    {/* Session Avatar */}
                    <Avatar className="w-9 h-9 shrink-0 rounded-full mt-0.5">
                      {item.session_avatar && <AvatarImage src={item.session_avatar} />}
                      <AvatarFallback className="bg-muted text-muted-foreground text-xs rounded-full">
                        {item.is_group ? (
                          <Users className="w-4 h-4" />
                        ) : (
                          <User className="w-4 h-4" />
                        )}
                      </AvatarFallback>
                    </Avatar>

                    {/* Content Details */}
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center justify-between gap-2 mb-1">
                        <div className="flex items-center gap-1.5 min-w-0">
                          <span className="font-semibold text-sm text-foreground truncate">
                            {item.session_name}
                          </span>
                          {item.is_group && (
                            <Badge variant="secondary" className="text-[10px] py-0 px-1.5 rounded">
                              群聊
                            </Badge>
                          )}
                          <span className="text-xs text-muted-foreground/70 truncate">
                            · {item.sender}
                          </span>
                        </div>
                        <span className="text-[11px] text-muted-foreground/60 shrink-0 flex items-center gap-1">
                          <Clock className="w-3 h-3" />
                          {item.time_str?.slice(0, 16) || "历史消息"}
                        </span>
                      </div>

                      {/* Snippet */}
                      <p className="text-xs text-foreground/80 leading-relaxed [overflow-wrap:anywhere] line-clamp-2">
                        {item.kind === "file" && (
                          <span className="inline-flex items-center gap-1 text-primary mr-1 font-medium">
                            <FileText className="w-3.5 h-3.5" /> [文件]
                          </span>
                        )}
                        {item.kind === "image" && (
                          <span className="inline-flex items-center gap-1 text-primary mr-1 font-medium">
                            <ImageIcon className="w-3.5 h-3.5" /> [图片]
                          </span>
                        )}
                        <HighlightedText text={item.snippet} query={query} />
                      </p>
                    </div>

                    <ChevronRight className="w-4 h-4 text-muted-foreground/40 self-center shrink-0" />
                  </div>
                )
              })}
          </div>

          {/* Footer Bar */}
          <div className="px-4 py-2.5 bg-muted/30 border-t border-border/40 flex items-center justify-between text-[11px] text-muted-foreground">
            <div className="flex items-center gap-3">
              <span>↑↓ 选择</span>
              <span>Enter 打开会话</span>
              <span>ESC 退出</span>
            </div>
            <span>Moect 全局极速搜索</span>
          </div>
        </motion.div>
      </div>
    </AnimatePresence>
  )
}
