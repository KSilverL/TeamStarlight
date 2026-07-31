// Mock data & PLATFORM_CONFIG
import type { Platform, PostStatus } from "./types";

export const PLATFORM_CONFIG: Record<
  Platform,
  { label: string; abbr: string; badge: string; dot: string }
> = {
  instagram: {
    label: "Instagram",
    abbr: "IG",
    badge: "bg-gradient-to-r from-purple-600 to-pink-600",
    dot: "bg-pink-500",
  },
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

export const MOCK_POSTS = [
  {
    id: "p1",
    platform: "Instagram",
    platformColor: "bg-gradient-to-r from-purple-600 to-pink-600",
    platformBadge: "bg-pink-600",
    abbr: "IG",
    date: "Jun 9, 2026",
    status: "pending" as PostStatus,
    text: "🌿 Meet your kitchen's new best friend — the Bamboo Kitchen Collection.\n\nCrafted from 100% organic bamboo, each piece is naturally antimicrobial, carbon-negative in production, and built to last a decade. Because sustainable living shouldn't mean settling for less. 🏡",
    hashtags: [
      "#EcoHome",
      "#BambooKitchen",
      "#SustainableLiving",
      "#ZeroWaste",
      "#GreenHome",
    ],
  },
  {
    id: "p2",
    platform: "LinkedIn",
    platformColor: "bg-blue-700",
    platformBadge: "bg-blue-600",
    abbr: "in",
    date: "Jun 9, 2026",
    status: "pending" as PostStatus,
    text: "The sustainable homewares market is projected to reach $150B by 2030 — and EcoHome Solutions is proud to be part of that shift.\n\nToday we're launching the Bamboo Kitchen Collection: premium products that prove sustainable materials can exceed conventional standards.",
    hashtags: [],
  },
  {
    id: "p3",
    platform: "TikTok",
    platformColor: "bg-[#1B1A17]",
    platformBadge: "bg-[#1B1A17]",
    abbr: "TK",
    date: "Jun 8, 2026",
    status: "pending" as PostStatus,
    text: "Hook: POV — you just replaced every plastic utensil in your kitchen 🎋\nBody: Bamboo is 3× stronger than steel by weight, grows back in months, and looks stunning on any countertop.\nCTA: Link in bio to shop the Bamboo Kitchen Collection.\nSound: Upbeat acoustic indie track",
    hashtags: ["#BambooLife", "#SustainableKitchen", "#EcoTok", "#GreenLiving"],
  },
  {
    id: "p4",
    platform: "X (Twitter)",
    platformColor: "bg-[#1B1A17]",
    platformBadge: "bg-[#1B1A17]",
    abbr: "X",
    date: "Jun 8, 2026",
    status: "pending" as PostStatus,
    text: "Your kitchen deserves better than plastic. 🌿\n\nThe EcoHome Bamboo Kitchen Collection — antimicrobial, carbon-negative, built to last. Shop now →",
    hashtags: ["#EcoHome", "#SustainableLiving"],
  },
  {
    id: "p5",
    platform: "Instagram",
    platformColor: "bg-gradient-to-r from-purple-600 to-pink-600",
    platformBadge: "bg-pink-600",
    abbr: "IG",
    date: "Jun 7, 2026",
    status: "pending" as PostStatus,
    text: "Small swaps, big impact. ♻️\n\nSwitch to bamboo and reduce your kitchen's plastic footprint by up to 80%. Our new collection makes it easy — and beautiful.",
    hashtags: [
      "#ZeroWaste",
      "#PlasticFree",
      "#EcoHome",
      "#BambooKitchen",
      "#ConsciousLiving",
      "#GreenHome",
    ],
  },
];

export const STATS = {
  postsCreated: 47,
  impressions: 128400,
  engagementRate: 4.2,
  approvalRate: 89,
  avgTimeToApprove: "14 min",
  topPlatform: "Instagram",
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
    { platform: "Instagram", posts: 18, color: "bg-pink-500" },
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

