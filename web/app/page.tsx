import HeroDive from "@/components/HeroDive";
import ProblemSection from "@/components/ProblemSection";
import HowItWorksSection from "@/components/HowItWorksSection";
import DemoSection from "@/components/DemoSection";
import InstallCompareSection from "@/components/InstallCompareSection";
import BackdropFX from "@/components/BackdropFX";

// Four beats. What it is, why the bug exists, how the check works and what one
// real session looks like, and how to install it. The middle beat carries the
// whole mechanism so the page never restates itself.
export default function Home() {
  return (
    <main className="relative">
      {/* Continuous, fixed backdrop — shared by every section so the background
          never abruptly "turns" between beats. Sections below sit transparent on
          top of this, so scrolling reads as one surface. */}
      <BackdropFX />
      {/* Hero feathers into transparency at its base so the dive melts into the
          backdrop with no hard black edge between the two. */}
      <div
        data-snap
        className="[mask-image:linear-gradient(to_bottom,#000_64%,transparent_100%)] [-webkit-mask-image:linear-gradient(to_bottom,#000_64%,transparent_100%)]"
      >
        <HeroDive />
      </div>
      <div data-snap>
        <ProblemSection />
      </div>
      {/* One beat: the three moves, then a recorded run of them. */}
      <section data-snap className="relative w-full">
        <HowItWorksSection />
        <DemoSection />
      </section>
      <InstallCompareSection />
    </main>
  );
}
