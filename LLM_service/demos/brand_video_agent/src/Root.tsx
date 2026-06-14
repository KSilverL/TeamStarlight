import "./index.css";
import { Composition } from "remotion";
import { MyComposition } from "./Composition";
import { DEFAULT_BRAND_PROPS } from "./types";

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition
        id="MyComp"
        component={MyComposition}
        durationInFrames={360}
        fps={30}
        width={1080}
        height={1920}
        defaultProps={DEFAULT_BRAND_PROPS}
      />
    </>
  );
};
