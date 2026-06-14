interface HeroProps {
  appCount: number;
}

export default function Hero({ appCount }: HeroProps) {
  return (
    <div className="hero">
      <h2>
        Discover Open-Source Android Apps
      </h2>
      <p>
        Browse {appCount} free &amp; open-source Android applications published
        on GitHub. Every download links to the official release — no
        redistribution, no middleman.
      </p>
    </div>
  );
}
