// Overlay is now a thin wrapper over Modal with slide-in sizing defaults.
// Kept for backward compatibility — prefer importing Modal directly.
import Modal from './Modal';

export default function Overlay({ width = '70%', height = '70%', ...props }) {
  return <Modal width={width} height={height} {...props} />;
}
