export default function App() {
  return (
    <div
      style={{
        background: "#07111d",
        minHeight: "100vh",
        color: "white",
        padding: "40px",
        fontFamily: "sans-serif",
      }}
    >
      <h1>🥖 Loaf Builder Toolkit</h1>

      <p>
        Open-source dashboard for exploring the Loaf Markets ecosystem.
      </p>

      <br />

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(3,1fr)",
          gap: "20px",
        }}
      >
        <div
          style={{
            background: "#132238",
            padding: "20px",
            borderRadius: "12px",
          }}
        >
          <h2>TVL</h2>
          <h3>$ --</h3>
        </div>

        <div
          style={{
            background: "#132238",
            padding: "20px",
            borderRadius: "12px",
          }}
        >
          <h2>Total Markets</h2>
          <h3>--</h3>
        </div>

        <div
          style={{
            background: "#132238",
            padding: "20px",
            borderRadius: "12px",
          }}
        >
          <h2>Supported Chains</h2>
          <h3>--</h3>
        </div>
      </div>
    </div>
  );
}