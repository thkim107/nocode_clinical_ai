import { useEffect } from "react";

interface Props {
  src: string;
}

export default function ImageViewer({ src }: Props) {
  useEffect(() => {
    return () => {
      URL.revokeObjectURL(src);
    };
  }, [src]);

  return (
    <div className="image-viewer">
      <img src={src} alt="preview" />
    </div>
  );
}
