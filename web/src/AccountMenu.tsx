import { LogOut, Settings2 } from 'lucide-react';
import { Link, useLocation } from 'react-router-dom';
import ActionMenu from './ActionMenu';

export default function AccountMenu({
  username,
  onLogout,
}: {
  username: string;
  onLogout: () => void;
}) {
  const location = useLocation();
  const avatar = (
    <span className="avatar" aria-hidden="true">
      {username.slice(0, 1).toUpperCase()}
    </span>
  );
  return (
    <ActionMenu
      label={`Меню профиля ${username}`}
      triggerClassName="account-line account-trigger"
      triggerContent={
        <>
          {avatar}
          <span className="account-name">
            {username}
            <small>Ваша мастерская</small>
          </span>
        </>
      }
      className="account-menu"
      placement="top-start"
    >
      {(close) => (
        <>
          <div className="account-menu-heading">
            {avatar}
            <span className="account-menu-username">{username}</span>
          </div>
          <div className="menu-separator" role="separator" />
          <Link
            role="menuitem"
            to="/settings"
            state={{ from: location.pathname + location.search + location.hash }}
            onClick={close}
          >
            <Settings2 size={18} /> Настройки
          </Link>
          <div className="menu-separator" role="separator" />
          <button
            role="menuitem"
            onClick={() => {
              close();
              onLogout();
            }}
          >
            <LogOut size={18} /> Выйти
          </button>
        </>
      )}
    </ActionMenu>
  );
}
