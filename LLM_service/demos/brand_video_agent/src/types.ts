export interface StatItem {
  value: string;
  label: string;
  icon: string;
}

export interface BrandProps {
  brandName: string;
  tagline: string;
  primaryColor: string;
  secondaryColor: string;
  accentColor: string;
  sectionLabel: string;
  stats: StatItem[];
  headline: string;
  subtext: string;
  ctaLabel: string;
  contact: string;
}

export const DEFAULT_BRAND_PROPS: BrandProps = {
  brandName: "APEX",
  tagline: "Elevate Your Brand",
  primaryColor: "#0f0f1a",
  secondaryColor: "#6c63ff",
  accentColor: "#ff6584",
  sectionLabel: "Why Choose Us",
  stats: [
    { value: "10K+", label: "Happy Clients", icon: "★" },
    { value: "99%", label: "Satisfaction Rate", icon: "◆" },
    { value: "5 YRS", label: "Industry Experience", icon: "▲" },
  ],
  headline: "Ready to Elevate?",
  subtext: "Join thousands of brands already growing with us.",
  ctaLabel: "Get Started Today",
  contact: "@apexbrand · apexbrand.com",
};
