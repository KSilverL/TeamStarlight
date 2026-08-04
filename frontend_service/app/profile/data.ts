// Mock data & PLATFORM_CONFIG
import type { Platform } from "./types";

export const PLATFORM_CONFIG: Record<
  Platform,
  { label: string; abbr: string; badge: string; dot: string }
> = {
  facebook: {
    label: "Facebook",
    abbr: "f",
    badge: "bg-[#1877F2]",
    dot: "bg-[#1877F2]",
  },
  linkedin: {
    label: "LinkedIn",
    abbr: "in",
    badge: "bg-blue-700",
    dot: "bg-blue-600",
  },
  tiktok: {
    label: "TikTok",
    abbr: "TK",
    badge: "bg-zinc-700",
    dot: "bg-zinc-500",
  },
  x: {
    label: "X (Twitter)",
    abbr: "X",
    badge: "bg-[#1B1A17]",
    dot: "bg-[#1B1A17]",
  },
};

export const STATS = {
  postsCreated: 47,
  impressions: 128400,
  engagementRate: 4.2,
  approvalRate: 89,
  avgTimeToApprove: "14 min",
  topPlatform: "Facebook",
  weeklyData: [
    { day: "Mon", posts: 3, impressions: 12400 },
    { day: "Tue", posts: 7, impressions: 18900 },
    { day: "Wed", posts: 5, impressions: 14200 },
    { day: "Thu", posts: 9, impressions: 27300 },
    { day: "Fri", posts: 11, impressions: 31800 },
    { day: "Sat", posts: 6, impressions: 15600 },
    { day: "Sun", posts: 6, impressions: 8200 },
  ],
  platformBreakdown: [
    { platform: "Facebook", posts: 18, color: "bg-[#1877F2]" },
    { platform: "LinkedIn", posts: 12, color: "bg-blue-500" },
    { platform: "TikTok", posts: 9, color: "bg-zinc-600" },
    { platform: "X (Twitter)", posts: 8, color: "bg-[#FF4800]" },
  ],
};

export const DEFAULT_BRAND = {
  name: "EcoHome Solutions",
  competitors: "Grove Collaborative, Package Free Shop, Bambu",
  description:
    "We sell sustainable bamboo home products designed for eco-conscious households. Our mission is to make sustainable living accessible and beautiful.",
  demographic:
    "Eco-conscious millennials aged 25–40, primarily urban, middle-to-high income, interested in sustainability and home design.",
  tone: "Warm, aspirational, and educational — we inspire rather than hard-sell.",
  topics:
    "Bamboo homewares, sustainable kitchen products, zero-waste living tips, product launches.",
  avoid: "Greenwashing language, aggressive CTAs, overly technical jargon.",
  notes:
    "Always emphasise carbon-negative production and the decade-long lifespan of our products.",
};

